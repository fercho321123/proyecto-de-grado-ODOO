from odoo import models, fields, api, _ 
from odoo.exceptions import UserError
from datetime import timedelta

class DevolucionProducto(models.Model):
    _name = 'pyme.devolucion'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Gestión de Devoluciones al Barril'
    _order = 'id desc'

    nombre = fields.Char(string='Referencia', required=True, copy=False, readonly=True, default='Nuevo')
    cliente_id = fields.Many2one('res.partner', string='Cliente', required=True, tracking=True)
    producto_id = fields.Many2one('product.product', string='Producto', required=True, tracking=True)
    cantidad = fields.Float(string='Cantidad', default=1.0, required=True, tracking=True)
    
    motivo = fields.Selection([
        ('dañado', 'Defecto de Fabricación'),
        ('incorrecto', 'Error en Pedido'),
        ('no_gusta', 'Inconformidad'),
        ('otros', 'Otros')
    ], string='Causal', required=True, tracking=True)
    
    descripcion_devolucion = fields.Text(string='Dictamen Técnico')
    imagen_ids = fields.One2many('pyme.devolucion.imagen', 'devolucion_id', string='Evidencias')
    
    estado = fields.Selection([
        ('borrador', 'Borrador'),
        ('proceso', 'En Validación'),
        ('finalizado', 'Finalizado'),
    ], default='borrador', tracking=True)

    resolucion = fields.Selection([
        ('dinero', 'Reembolso Solicitado'),
        ('reemplazo', 'Sustitución Física'),
        ('saldo', 'Nota de Crédito/Saldo')
    ], string='Resolución', readonly=True, tracking=True)

    # --- CAMPOS CALCULADOS CON ALMACENAMIENTO PARA FILTROS ---
    valor_estimado = fields.Float(string="Valor Impacto", compute="_compute_valor_estimado", store=True)
    dias_retraso = fields.Integer(string='Días Retraso', compute='_compute_dias_retraso', store=True)
    tiempo_respuesta_texto = fields.Char(string='Tiempo de Respuesta', compute='_compute_tiempo_respuesta_texto', store=True)

    @api.depends('create_date', 'write_date', 'estado')
    def _compute_tiempo_respuesta_texto(self):
        for reg in self:
            if reg.estado == 'finalizado' and reg.create_date:
                diff = reg.write_date - reg.create_date
                reg.tiempo_respuesta_texto = f"{diff.days} días"
            else:
                reg.tiempo_respuesta_texto = "En proceso"

    @api.depends('create_date', 'estado')
    def _compute_dias_retraso(self):
        for reg in self:
            if reg.estado != 'finalizado' and reg.create_date:
                diff = fields.Date.today() - reg.create_date.date()
                reg.dias_retraso = diff.days
            else:
                reg.dias_retraso = 0

    @api.depends('producto_id', 'cantidad')
    def _compute_valor_estimado(self):
        for reg in self:
            reg.valor_estimado = (reg.producto_id.list_price or 0.0) * reg.cantidad

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('nombre', 'Nuevo') == 'Nuevo':
                vals['nombre'] = self.env['ir.sequence'].sudo().next_by_code('pyme.devolucion') or 'Nuevo'
        return super(DevolucionProducto, self).create(vals_list)

    def boton_confirmar(self):
        self.write({'estado': 'proceso'})

    def _ejecutar_logistica(self):
        """Mantiene la creación de albaranes de entrada"""
        for reg in self:
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', reg.cliente_id.company_id.id or self.env.company.id)], limit=1)
            picking_type = self.env['stock.picking.type'].search([('code', '=', 'incoming'), ('warehouse_id', '=', warehouse.id)], limit=1)
            if picking_type:
                picking = self.env['stock.picking'].sudo().create({
                    'partner_id': reg.cliente_id.id,
                    'picking_type_id': picking_type.id,
                    'location_id': reg.cliente_id.property_stock_customer.id,
                    'location_dest_id': picking_type.default_location_dest_id.id,
                    'origin': reg.nombre,
                    'company_id': warehouse.company_id.id,
                })
                self.env['stock.move'].sudo().create({
                    'name': reg.nombre,
                    'product_id': reg.producto_id.id,
                    'product_uom_qty': reg.cantidad,
                    'product_uom': reg.producto_id.uom_id.id,
                    'picking_id': picking.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                    'company_id': warehouse.company_id.id,
                })
                picking.action_confirm()

    def boton_solicitar_reembolso(self):
        """CORREGIDO: Manejo de multi-compañía para evitar RPC_ERROR de empresas incompatibles"""
        self._ejecutar_logistica()
        for reg in self:
            # Forzamos la compañía del registro o del cliente para evitar conflictos contables
            company_id = reg.cliente_id.company_id.id or self.env.company.id
            
            # Buscamos el diario de ventas que pertenezca exclusivamente a esa empresa
            journal = self.env['account.journal'].sudo().search([
                ('type', '=', 'sale'),
                ('company_id', '=', company_id)
            ], limit=1)
            
            if not journal:
                raise UserError(_("No se encontró un diario de ventas para la compañía: %s") % company_id)

            # Determinamos la cuenta contable (debe ser de la misma empresa)
            account_id = reg.producto_id.property_account_income_id.id or journal.default_account_id.id
            
            if not account_id:
                raise UserError(_("Configure una cuenta de ingresos en el producto o en el diario."))

            # Creación de la Factura Rectificativa (Refund)
            invoice_vals = {
                'move_type': 'out_refund',
                'partner_id': reg.cliente_id.id,
                'journal_id': journal.id,
                'company_id': company_id, # Asignación explícita
                'invoice_origin': reg.nombre,
                'invoice_date': fields.Date.today(),
                'invoice_line_ids': [(0, 0, {
                    'product_id': reg.producto_id.id,
                    'quantity': reg.cantidad,
                    'price_unit': reg.producto_id.list_price,
                    'name': f'Reembolso: {reg.nombre}',
                    'account_id': account_id,
                })],
            }

            invoice = self.env['account.move'].sudo().create(invoice_vals)
            
            # Adjuntar evidencias a la factura
            for img in reg.imagen_ids:
                self.env['ir.attachment'].sudo().create({
                    'name': f"Evidencia_{img.nombre}",
                    'type': 'binary',
                    'datas': img.archivo,
                    'res_model': 'account.move',
                    'res_id': invoice.id,
                })

            try:
                invoice.action_post()
            except Exception as e:
                reg.message_post(body=_("La factura se creó en borrador. Error al validar: %s") % str(e))

            reg.write({'resolucion': 'dinero', 'estado': 'finalizado'})

    def boton_reemplazar_producto(self):
        self._ejecutar_logistica()
        self.write({'resolucion': 'reemplazo', 'estado': 'finalizado'})

    def boton_generar_saldo(self):
        self._ejecutar_logistica()
        self.write({'resolucion': 'saldo', 'estado': 'finalizado'})

class DevolucionImagen(models.Model):
    _name = 'pyme.devolucion.imagen'
    _description = 'Evidencias de Devolución'
    devolucion_id = fields.Many2one('pyme.devolucion', ondelete='cascade')
    nombre = fields.Char(string='Nombre', required=True)
    archivo = fields.Binary(string='Archivo', required=True)