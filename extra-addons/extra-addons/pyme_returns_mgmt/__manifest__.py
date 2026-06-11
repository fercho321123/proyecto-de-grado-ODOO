{
    'name': 'Gestión Profesional de Devoluciones',
    'version': '1.3',
    'category': 'Operations/Logistics',
    'summary': 'Sistema de Logística Inversa para Hamburgueserías',
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