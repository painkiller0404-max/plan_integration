from odoo import models, fields, api
from odoo.exceptions import UserError


class IntegrationQcm(models.Model):
    """
    QCM (Questionnaire à Choix Multiple) definition.
    HR creates and manages QCMs for each evaluation stage.
    """
    _name = 'integration.qcm'
    _description = 'QCM - Questionnaire à Choix Multiple'
    _order = 'qcm_type, name'

    name = fields.Char(string='Nom du QCM', required=True)
    qcm_type = fields.Selection([
        ('rh', 'Test RH - Culture & Valeurs'),
        ('hse', 'Évaluation HSE'),
        ('immersion', 'Évaluation Immersion'),
    ], string='Type de test', required=True)
    pass_score = fields.Float(
        string='Score minimal pour réussir (/10)',
        default=6.0,
        help="Score minimum (sur 10) requis pour passer cette étape.",
    )
    question_ids = fields.One2many(
        'integration.qcm.question', 'qcm_id', string='Questions'
    )
    question_count = fields.Integer(
        compute='_compute_question_count', string='Nbre de questions'
    )
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes / Instructions')

    @api.depends('question_ids')
    def _compute_question_count(self):
        for rec in self:
            rec.question_count = len(rec.question_ids)

    @api.constrains('question_ids')
    def _check_questions_have_correct_answer(self):
        for rec in self:
            for q in rec.question_ids:
                if q.answer_ids and not q.answer_ids.filtered('is_correct'):
                    raise UserError(
                        f"La question « {q.question_text} » n'a aucune bonne réponse définie."
                    )


class IntegrationQcmQuestion(models.Model):
    """A single question within a QCM."""
    _name = 'integration.qcm.question'
    _description = 'Question QCM'
    _order = 'sequence, id'

    qcm_id = fields.Many2one(
        'integration.qcm', string='QCM', required=True, ondelete='cascade'
    )
    sequence = fields.Integer(default=10)
    question_text = fields.Text(string='Question', required=True)
    answer_ids = fields.One2many(
        'integration.qcm.answer', 'question_id', string='Réponses possibles'
    )
    max_points = fields.Integer(
        string='Points', default=1,
        help="Nombre de points accordés si la bonne réponse est choisie."
    )


class IntegrationQcmAnswer(models.Model):
    """A possible answer choice for a QCM question."""
    _name = 'integration.qcm.answer'
    _description = 'Réponse QCM'
    _rec_name = 'answer_text'
    _order = 'sequence, id'

    question_id = fields.Many2one(
        'integration.qcm.question', string='Question', required=True, ondelete='cascade'
    )
    sequence = fields.Integer(default=10)
    answer_text = fields.Char(string='Réponse', required=True)
    is_correct = fields.Boolean(string='Bonne réponse', default=False)
