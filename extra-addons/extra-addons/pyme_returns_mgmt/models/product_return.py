from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta


class DevolucionProducto(models.Model):
    _name = 'pyme.devolucion'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Gestión de Devoluciones de Productos'
    _order = 'id desc'

    # ─────────────────────────────────────────────
    #  CAMPOS BÁSICOS
    # ─────────────────────────────────────────────
    nombre = fields.Char(
        string='Referencia', required=True, copy=False,
        readonly=True, default='Nuevo'
    )
    cliente_id = fields.Many2one(
        'res.partner', string='Cliente', required=True, tracking=True
    )
    responsable_id = fields.Many2one(
        'res.users', string='Responsable', tracking=True,
        default=lambda self: self.env.user
    )
    producto_id = fields.Many2one(
        'product.product', string='Producto', required=True, tracking=True
    )
    cantidad = fields.Float(
        string='Cantidad', default=1.0, required=True, tracking=True
    )
    currency_id = fields.Many2one(
        'res.currency', string='Moneda',
        default=lambda self: self.env.company.currency_id
    )

    motivo = fields.Selection([
        ('dañado',     'Defecto de Fabricación'),
        ('incorrecto', 'Error en Pedido'),
        ('no_gusta',   'Inconformidad'),
        ('otros',      'Otros'),
    ], string='Causal', required=True, tracking=True)

    descripcion_devolucion = fields.Text(string='Dictamen Técnico')
    imagen_ids = fields.One2many(
        'pyme.devolucion.imagen', 'devolucion_id', string='Evidencias'
    )

    estado = fields.Selection([
        ('borrador',   'Borrador'),
        ('proceso',    'En Validación'),
        ('finalizado', 'Finalizado'),
        ('cancelado',  'Cancelado'),
    ], default='borrador', tracking=True, string='Estado')

    resolucion = fields.Selection([
        ('dinero',       'Reembolso Solicitado'),
        ('reemplazo',    'Sustitución Física'),
        ('saldo',        'Nota de Crédito/Saldo'),
        ('sin_garantia', 'Sin Garantía'),
    ], string='Resolución', readonly=True, tracking=True)

    # ─────────────────────────────────────────────
    #  RELACIONES A REGISTROS GENERADOS
    # ─────────────────────────────────────────────
    picking_ids = fields.Many2many(
        'stock.picking', string='Albaranes',
        copy=False, readonly=True
    )
    invoice_ids = fields.Many2many(
        'account.move', string='Facturas/Notas de Crédito',
        copy=False, readonly=True
    )
    picking_count = fields.Integer(
        string='# Albaranes', compute='_compute_counts'
    )
    invoice_count = fields.Integer(
        string='# Facturas', compute='_compute_counts'
    )

    # ─────────────────────────────────────────────
    #  CAMPOS CALCULADOS (store=True para filtros)
    # ─────────────────────────────────────────────
    valor_estimado = fields.Monetary(
        string='Valor Impacto',
        compute='_compute_valor_estimado',
        store=True,
        currency_field='currency_id',
    )
    dias_retraso = fields.Integer(
        string='Días Retraso',
        compute='_compute_dias_retraso',
        store=True,
    )
    tiempo_respuesta_texto = fields.Char(
        string='Tiempo de Respuesta',
        compute='_compute_tiempo_respuesta_texto',
        store=True,
    )

    # ─────────────────────────────────────────────
    #  COMPUTES
    # ─────────────────────────────────────────────
    @api.depends('picking_ids', 'invoice_ids')
    def _compute_counts(self):
        for rec in self:
            rec.picking_count = len(rec.picking_ids)
            rec.invoice_count = len(rec.invoice_ids)

    @api.depends('create_date', 'write_date', 'estado')
    def _compute_tiempo_respuesta_texto(self):
        for rec in self:
            if rec.estado == 'finalizado' and rec.create_date:
                diff = rec.write_date - rec.create_date
                rec.tiempo_respuesta_texto = f"{diff.days} día(s)"
            else:
                rec.tiempo_respuesta_texto = "En proceso"

    @api.depends('create_date', 'estado')
    def _compute_dias_retraso(self):
        for rec in self:
            if rec.estado not in ('finalizado', 'cancelado') and rec.create_date:
                diff = fields.Date.today() - rec.create_date.date()
                rec.dias_retraso = diff.days
            else:
                rec.dias_retraso = 0

    @api.depends('producto_id', 'cantidad')
    def _compute_valor_estimado(self):
        for rec in self:
            rec.valor_estimado = (rec.producto_id.list_price or 0.0) * rec.cantidad

    # ─────────────────────────────────────────────
    #  SECUENCIA AL CREAR
    # ─────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('nombre', 'Nuevo') == 'Nuevo':
                vals['nombre'] = (
                    self.env['ir.sequence'].sudo().next_by_code('pyme.devolucion')
                    or 'Nuevo'
                )
        return super().create(vals_list)

    # ─────────────────────────────────────────────
    #  ACCIONES DE BOTONES
    # ─────────────────────────────────────────────
    def boton_confirmar(self):
        """Valida datos obligatorios antes de pasar a 'En Validación'."""
        for rec in self:
            if not rec.descripcion_devolucion:
                raise ValidationError(
                    _("Debe completar el Dictamen Técnico antes de validar la recepción.")
                )
        self.write({'estado': 'proceso'})

    def boton_cancelar(self):
        for rec in self:
            if rec.estado == 'finalizado':
                raise UserError(_("No se puede cancelar una devolución ya finalizada."))
        self.write({'estado': 'cancelado'})

    def boton_restablecer(self):
        """Regresa a borrador desde cancelado."""
        self.write({'estado': 'borrador'})

    def boton_sin_garantia(self):
        """Cierra el caso indicando que el producto no tiene garantía aplicable."""
        for rec in self:
            if rec.estado == 'finalizado':
                raise UserError(
                    _("No se puede marcar como Sin Garantía una devolución ya finalizada.")
                )
        self.write({'resolucion': 'sin_garantia', 'estado': 'finalizado'})
        for rec in self:
            rec.message_post(
                body=_("🚫 Resolución: Producto sin garantía aplicable. Caso cerrado.")
            )

    # ─────────────────────────────────────────────
    #  LÓGÍSTICA: CREACIÓN DE ALBARÁN DE ENTRADA
    # ─────────────────────────────────────────────
    def _ejecutar_logistica(self):
        """Crea un albarán de entrada por devolución (solo si aún no existe)."""
        for rec in self:
            # Evitar duplicados
            if rec.picking_ids:
                continue

            company_id = self.env.company.id
            warehouse = self.env['stock.warehouse'].search(
                [('company_id', '=', company_id)], limit=1
            )
            if not warehouse:
                raise UserError(_("No se encontró un almacén configurado para la compañía."))

            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'incoming'),
                ('warehouse_id', '=', warehouse.id),
            ], limit=1)
            if not picking_type:
                raise UserError(_("No se encontró un tipo de operación de recepción."))

            customer_location = self.env.ref('stock.stock_location_customers')

            picking = self.env['stock.picking'].sudo().create({
                'partner_id': rec.cliente_id.id,
                'picking_type_id': picking_type.id,
                'location_id': customer_location.id,
                'location_dest_id': picking_type.default_location_dest_id.id,
                'origin': rec.nombre,
                'company_id': company_id,
            })
            self.env['stock.move'].sudo().create({
                'name': f"Devolución: {rec.nombre}",
                'product_id': rec.producto_id.id,
                'product_uom_qty': rec.cantidad,
                'product_uom': rec.producto_id.uom_id.id,
                'picking_id': picking.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'company_id': company_id,
            })
            picking.action_confirm()
            rec.picking_ids = [(4, picking.id)]

            rec.message_post(
                body=_("✅ Albarán de recepción creado: <b>%s</b>") % picking.name
            )

    # ─────────────────────────────────────────────
    #  RESOLUCIONES
    # ─────────────────────────────────────────────
    def boton_solicitar_reembolso(self):
        """Crea nota de crédito (out_refund) y finaliza la devolución."""
        self._ejecutar_logistica()
        for rec in self:
            company_id = self.env.company.id

            journal = self.env['account.journal'].sudo().search([
                ('type', '=', 'sale'),
                ('company_id', '=', company_id),
            ], limit=1)
            if not journal:
                raise UserError(
                    _("No se encontró un diario de ventas para la compañía.")
                )

            account_id = (
                rec.producto_id.property_account_income_id.id
                or journal.default_account_id.id
            )
            if not account_id:
                raise UserError(
                    _("Configure una cuenta de ingresos en el producto o en el diario.")
                )

            invoice = self.env['account.move'].sudo().create({
                'move_type': 'out_refund',
                'partner_id': rec.cliente_id.id,
                'journal_id': journal.id,
                'company_id': company_id,
                'invoice_origin': rec.nombre,
                'invoice_date': fields.Date.today(),
                'invoice_line_ids': [(0, 0, {
                    'product_id': rec.producto_id.id,
                    'quantity': rec.cantidad,
                    'price_unit': rec.producto_id.list_price,
                    'name': f'Reembolso: {rec.nombre}',
                    'account_id': account_id,
                })],
            })

            # Adjuntar evidencias a la factura
            for img in rec.imagen_ids:
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
                rec.message_post(
                    body=_("La factura se creó en borrador. Error al confirmar: %s") % str(e)
                )

            rec.invoice_ids = [(4, invoice.id)]
            rec.write({'resolucion': 'dinero', 'estado': 'finalizado'})
            rec.message_post(
                body=_("💰 Reembolso procesado. Nota de crédito: <b>%s</b>") % invoice.name
            )

    def boton_reemplazar_producto(self):
        self._ejecutar_logistica()
        self.write({'resolucion': 'reemplazo', 'estado': 'finalizado'})
        for rec in self:
            rec.message_post(body=_("🔄 Resolución: Sustitución física del producto."))

    def boton_generar_saldo(self):
        self._ejecutar_logistica()
        self.write({'resolucion': 'saldo', 'estado': 'finalizado'})
        for rec in self:
            rec.message_post(body=_("📋 Resolución: Nota de crédito / saldo a favor."))

    # ─────────────────────────────────────────────
    #  SMART BUTTONS – acciones de ventana
    # ─────────────────────────────────────────────
    def action_ver_albaranes(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Albaranes'),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.picking_ids.ids)],
        }

    def action_ver_facturas(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Facturas / Notas de Crédito'),
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.invoice_ids.ids)],
        }


class DevolucionImagen(models.Model):
    _name = 'pyme.devolucion.imagen'
    _description = 'Evidencias de Devolución'

    devolucion_id = fields.Many2one('pyme.devolucion', ondelete='cascade')
    nombre = fields.Char(string='Nombre', required=True)
    archivo = fields.Binary(string='Archivo', required=True)
