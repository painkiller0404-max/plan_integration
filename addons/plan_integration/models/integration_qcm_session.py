from odoo import models, fields, api
from odoo.exceptions import UserError


class IntegrationQcmSession(models.Model):
    """
    A new hire's attempt at a specific QCM.
    One session is created per QCM per integration plan.
    Score is computed automatically from responses.
    """
    _name = 'integration.qcm.session'
    _description = 'Session QCM'
    _order = 'date_start desc, id desc'
    _inherit = ['mail.thread']

    name = fields.Char(
        string='Référence', compute='_compute_name', store=True
    )
    plan_id = fields.Many2one(
        'integration.plan', string="Plan d'Intégration",
        required=True, ondelete='cascade', index=True
    )
    qcm_id = fields.Many2one(
        'integration.qcm', string='QCM', required=True
    )
    qcm_type = fields.Selection(
        related='qcm_id.qcm_type', string='Type', store=True, readonly=True
    )
    pass_score = fields.Float(
        related='qcm_id.pass_score', string='Score requis', readonly=True
    )
    user_id = fields.Many2one(
        'res.users', string='Candidat', default=lambda self: self.env.user
    )

    state = fields.Selection([
        ('draft', 'Non démarré'),
        ('in_progress', 'En cours'),
        ('done', 'Terminé'),
    ], string='État', default='draft', tracking=True)

    date_start = fields.Datetime(string='Date de début')
    date_end = fields.Datetime(string='Date de fin')

    response_ids = fields.One2many(
        'integration.qcm.response', 'session_id', string='Réponses'
    )
    response_count = fields.Integer(
        compute='_compute_response_count', string='Nbre réponses'
    )

    # ── Scoring ──────────────────────────────────────────────────────────────
    points_earned = fields.Float(
        string='Points obtenus', compute='_compute_score', store=True
    )
    points_total = fields.Float(
        string='Points total', compute='_compute_score', store=True
    )
    score = fields.Float(
        string='Score (/10)', compute='_compute_score', store=True,
        help="Score calculé automatiquement sur 10."
    )
    passed = fields.Boolean(
        string='Réussi', compute='_compute_score', store=True
    )

    # ─────────────────────────────────────────────────────────────────────────

    @api.depends('plan_id', 'qcm_id')
    def _compute_name(self):
        for rec in self:
            plan = rec.plan_id.name or ''
            qcm = rec.qcm_id.name or ''
            rec.name = f"{plan} – {qcm}" if plan and qcm else plan or qcm or 'Session QCM'

    @api.depends('response_ids')
    def _compute_response_count(self):
        for rec in self:
            rec.response_count = len(rec.response_ids)

    @api.depends(
        'response_ids.points_earned',
        'qcm_id.question_ids.max_points',
        'qcm_id.pass_score',
        'state',
    )
    def _compute_score(self):
        for rec in self:
            total = sum(rec.qcm_id.question_ids.mapped('max_points')) or 0
            earned = sum(rec.response_ids.mapped('points_earned')) or 0
            rec.points_total = total
            rec.points_earned = earned
            if total > 0:
                rec.score = round((earned / total) * 10, 2)
            else:
                rec.score = 0.0
            rec.passed = rec.score >= (rec.qcm_id.pass_score or 6.0)

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_start(self):
        """Start the QCM session: create blank response records for each question."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError("Cette session a déjà été démarrée.")
            if not rec.qcm_id.question_ids:
                raise UserError(
                    f"Le QCM « {rec.qcm_id.name} » ne contient aucune question."
                )
            # Create one response record per question
            for question in rec.qcm_id.question_ids.sorted('sequence'):
                self.env['integration.qcm.response'].create({
                    'session_id': rec.id,
                    'question_id': question.id,
                })
            rec.state = 'in_progress'
            rec.date_start = fields.Datetime.now()
        # Return the session form so the new hire can answer questions
        return {
            'name': "Répondre au QCM",
            'type': 'ir.actions.act_window',
            'res_model': 'integration.qcm.session',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_submit(self):
        """Submit the QCM session and compute the final score."""
        for rec in self:
            if rec.state != 'in_progress':
                raise UserError("Cette session n'est pas en cours.")
            unanswered = rec.response_ids.filtered(
                lambda r: not r.selected_answer_id
            )
            if unanswered:
                raise UserError(
                    f"Veuillez répondre à toutes les questions avant de soumettre. "
                    f"({len(unanswered)} réponse(s) manquante(s))"
                )
            rec.state = 'done'
            rec.date_end = fields.Datetime.now()
        return True


class IntegrationQcmResponse(models.Model):
    """
    A single question response within a QCM session.
    Points are automatically calculated based on the selected answer.
    """
    _name = 'integration.qcm.response'
    _description = 'Réponse à une question QCM'
    _order = 'question_id'

    session_id = fields.Many2one(
        'integration.qcm.session', string='Session',
        required=True, ondelete='cascade', index=True
    )
    question_id = fields.Many2one(
        'integration.qcm.question', string='Question', required=True
    )
    question_text = fields.Text(
        related='question_id.question_text', string='Énoncé', readonly=True
    )
    max_points = fields.Integer(
        related='question_id.max_points', string='Points max', readonly=True
    )
    selected_answer_id = fields.Many2one(
        'integration.qcm.answer',
        string='Réponse choisie',
        domain="[('question_id', '=', question_id)]",
    )
    is_correct = fields.Boolean(
        string='Correcte', compute='_compute_is_correct', store=True
    )
    points_earned = fields.Float(
        string='Points obtenus', compute='_compute_is_correct', store=True
    )

    @api.depends('selected_answer_id', 'selected_answer_id.is_correct', 'question_id.max_points')
    def _compute_is_correct(self):
        for rec in self:
            is_correct = bool(
                rec.selected_answer_id and rec.selected_answer_id.is_correct
            )
            rec.is_correct = is_correct
            rec.points_earned = float(rec.question_id.max_points) if is_correct else 0.0
