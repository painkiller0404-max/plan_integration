{
    'name': "Plan d'Intégration",
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Gestion du parcours d'intégration des nouveaux recrus",
    'description': """
        Module de gestion du parcours d'intégration des nouveaux collaborateurs.
        Supporte deux catégories d'employés :
        - Opérateurs / Opératrices
        - Maîtrise / Cadres

        Fonctionnalités :
        - Suivi du parcours selon le diagramme BPMN validé
        - QCM notés automatiquement (RH, HSE, Immersion)
        - Routage automatique selon les scores (>= 6 ou < 6)
        - Avis RH pour les décisions de branche
        - Interface tablette pour les opérateurs
    """,
    'author': "GDS",
    'depends': ['base', 'mail', 'hr'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/qcm_portal_templates.xml',
        'views/integration_qcm_views.xml',
        'views/integration_qcm_session_views.xml',
        'views/integration_plan_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'sequence': 1,
}
