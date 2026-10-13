{
    'name': 'Gestión Profesional de Devoluciones',
    'version': '1.4',
    'category': 'Operations/Logistics',
    'summary': 'Sistema de Logística Inversa para PYMES Comerciales',
    'license': 'LGPL-3',
    'description': """
        Módulo para la gestión integral de devoluciones de productos en PYMES.
        Permite registrar, controlar y hacer seguimiento a solicitudes de devolución,
        generando comprobantes PDF y conectando con contabilidad e inventario.
    """,
    'author': 'PYME Returns Team',
    'depends': ['base', 'stock', 'mail', 'account', 'product'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/product_return_views.xml',
        'report/product_return_report.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
