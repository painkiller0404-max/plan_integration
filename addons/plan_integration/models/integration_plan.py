from odoo import models, fields, api
from odoo.exceptions import UserError

# ── State constants ──────────────────────────────────────────────────────────

STATE_SELECTION = [
    ('nouveau', 'Nouveau'),
    ('culture_valeurs', 'Culture et Valeurs'),
    ('formation_hse_theorique', 'Formation Théorique HSE'),
    ('modalite_rh', 'Modalité RH'),
    ('formation_hse_pratique', 'Formation Pratique HSE'),
    ('evaluation_hse', 'Évaluation HSE'),
    ('presentation', 'Présentation Physique'),
    ('immersion', 'Immersion'),
    ('evaluation_immersion', 'Évaluation Immersion'),        # Operators only
    ('rapport_integration', "Rapport d'Intégration"),        # Executives only
    # ── Terminal states ──────────────────────────────────────────────────────
    ('valide', 'Validé ✓'),
    ('plan_formation', 'Plan de Formation'),
    ('periode_essai_non_concluante', "Période d'Essai Non Concluante"),
    ('transfert_autre_poste', 'Transfert Vers un Autre Poste'),
]

TERMINAL_STATES = {'valide', 'plan_formation', 'periode_essai_non_concluante', 'transfert_autre_poste'}

# Ordered stages per category (decision gates handled separately)
OPERATOR_FLOW = [
    'nouveau', 'culture_valeurs', 'formation_hse_theorique', 'modalite_rh',
    'formation_hse_pratique', 'evaluation_hse', 'presentation',
    'immersion', 'evaluation_immersion',
]

EXECUTIVE_FLOW = [
    'nouveau', 'culture_valeurs', 'formation_hse_theorique', 'modalite_rh',
    'formation_hse_pratique', 'evaluation_hse', 'presentation',
    'immersion', 'rapport_integration', 'plan_formation',
]

# Stages that trigger a decision gate before advancing
OPERATOR_GATES = {'culture_valeurs', 'evaluation_hse', 'evaluation_immersion'}
EXECUTIVE_GATES = {'evaluation_hse'}


class IntegrationPlan(models.Model):
    """
    Main model: one record per new hire's integration journey.
    Tracks the complete BPMN lifecycle with automatic QCM-score-based routing.
    """
    _name = 'integration.plan'
    _description = "Plan d'Intégration"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'hire_date desc, id desc'
    _rec_name = 'name'

    # ── Identity ─────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Référence', required=True, copy=False,
        readonly=True, default='Nouveau',
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employé', required=True, tracking=True
    )
    employee_category = fields.Selection([
        ('operator', 'Opérateur / Opératrice'),
        ('executive', 'Maîtrise / Cadre'),
    ], string='Catégorie', required=True, tracking=True)
    hire_date = fields.Date(
        string="Date d'embauche", required=True,
        default=fields.Date.today, tracking=True
    )
    department_id = fields.Many2one(
        'hr.department', string='Département',
        related='employee_id.department_id', store=True
    )
    job_position = fields.Char(
        string='Poste',
        related='employee_id.job_title', store=True
    )

    # ── Responsible people ────────────────────────────────────────────────────
    responsible_hr_id = fields.Many2one(
        'res.users', string='Responsable RH',
        domain=[('share', '=', False)], tracking=True
    )
    manager_id = fields.Many2one(
        'res.users', string='Manager',
        domain=[('share', '=', False)], tracking=True
    )

    # ── State machine ─────────────────────────────────────────────────────────
    state = fields.Selection(
        STATE_SELECTION,
        string='Étape', default='nouveau',
        required=True, tracking=True,
    )
    is_terminal = fields.Boolean(
        compute='_compute_is_terminal', store=True,
        string='Terminé',
    )

    # HR opinion — used at decision gates when a score is < 6
    hr_opinion = fields.Selection([
        ('positive', 'Positif — continuer / repêcher'),
        ('negative', 'Négatif — mettre fin à la période'),
    ], string='Avis RH', tracking=True,
        help="Requis uniquement quand un score QCM est inférieur au seuil (6/10).")

    # Rapport d'intégration (executives only, stage rapport_integration)
    rapport_integration = fields.Html(
        string="Rapport d'Intégration",
        help="Rédigé par le candidat cadre lors de la phase d'immersion.",
    )
    notes = fields.Html(string='Notes RH')

    # ── QCM sessions ──────────────────────────────────────────────────────────
    qcm_session_ids = fields.One2many(
        'integration.qcm.session', 'plan_id', string='Sessions QCM'
    )
    qcm_session_count = fields.Integer(
        compute='_compute_qcm_session_count', string='QCM'
    )

    # ── Computed scores (from latest DONE session per type) ───────────────────
    score_rh = fields.Float(
        string='Score RH (/10)', compute='_compute_scores', store=True, digits=(16, 2)
    )
    score_hse = fields.Float(
        string='Score HSE (/10)', compute='_compute_scores', store=True, digits=(16, 2)
    )
    score_immersion = fields.Float(
        string='Score Immersion (/10)', compute='_compute_scores', store=True, digits=(16, 2)
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Computed fields
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends('state')
    def _compute_is_terminal(self):
        for rec in self:
            rec.is_terminal = rec.state in TERMINAL_STATES

    @api.depends('qcm_session_ids')
    def _compute_qcm_session_count(self):
        for rec in self:
            rec.qcm_session_count = len(rec.qcm_session_ids)

    @api.depends(
        'qcm_session_ids.score',
        'qcm_session_ids.qcm_type',
        'qcm_session_ids.state',
    )
    def _compute_scores(self):
        for rec in self:
            done_sessions = rec.qcm_session_ids.filtered(lambda s: s.state == 'done')
            rec.score_rh = _latest_score(done_sessions, 'rh')
            rec.score_hse = _latest_score(done_sessions, 'hse')
            rec.score_immersion = _latest_score(done_sessions, 'immersion')

    # ─────────────────────────────────────────────────────────────────────────
    # ORM overrides
    # ─────────────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('integration.plan')
                    or 'Nouveau'
                )
        return super().create(vals_list)

    # ─────────────────────────────────────────────────────────────────────────
    # State machine actions
    # ─────────────────────────────────────────────────────────────────────────

    def action_next_stage(self):
        """Advance the integration plan to the next BPMN stage.

        At decision gates (after scoring QCMs), the routing is done
        automatically based on the score. If the score is below the threshold,
        the hr_opinion field is required to determine the branch.
        """
        self.ensure_one()
        if self.state in TERMINAL_STATES:
            raise UserError("Ce plan est déjà dans un état terminal.")
        self._advance_state()

    def action_reset_to_nouveau(self):
        """Reset the plan to the initial state (for testing / corrections)."""
        self.ensure_one()
        self.state = 'nouveau'
        self.hr_opinion = False
        self.message_post(body="Plan réinitialisé à l'état initial.")

    def action_view_qcm_sessions(self):
        return {
            'name': 'Sessions QCM',
            'type': 'ir.actions.act_window',
            'res_model': 'integration.qcm.session',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Internal state machine helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _advance_state(self):
        """Core state machine dispatcher."""
        current = self.state
        is_operator = self.employee_category == 'operator'

        # ── Decision gates ────────────────────────────────────────────────────
        if current == 'culture_valeurs' and is_operator:
            return self._gate_culture_valeurs()
        if current == 'evaluation_hse':
            return self._gate_evaluation_hse()
        if current == 'evaluation_immersion' and is_operator:
            return self._gate_evaluation_immersion()

        # ── Linear advance ────────────────────────────────────────────────────
        flow = OPERATOR_FLOW if is_operator else EXECUTIVE_FLOW
        if current in flow:
            idx = flow.index(current)
            if idx + 1 < len(flow):
                next_state = flow[idx + 1]
                self.state = next_state
                self.hr_opinion = False   # Reset opinion for fresh gate
            else:
                raise UserError("Ce plan est déjà à la dernière étape du flux.")
        else:
            raise UserError(
                f"Impossible d'avancer depuis l'état « {dict(STATE_SELECTION).get(current, current)} »."
            )

    def _gate_culture_valeurs(self):
        """
        Gate after Culture & Valeurs (operators only).
        Requires a completed RH QCM session with a score.
        - score_rh >= 6  → Formation Théorique HSE
        - score_rh <  6 + Avis HR positif  → Transfert vers un autre poste
        - score_rh <  6 + Avis HR négatif  → Période d'essai non concluante
        """
        self._require_qcm_done('rh', "Culture & Valeurs")
        if self.score_rh >= 6.0:
            self.state = 'formation_hse_theorique'
            self.hr_opinion = False
        else:
            opinion = self._require_hr_opinion(
                f"Score RH = {self.score_rh}/10 (< 6). "
                "Veuillez saisir l'avis RH avant de continuer."
            )
            if opinion == 'negative':
                self.state = 'periode_essai_non_concluante'
            else:
                self.state = 'transfert_autre_poste'

    def _gate_evaluation_hse(self):
        """
        Gate after Évaluation HSE (both categories).
        - score_hse >= 6  → Présentation Physique
        - score_hse <  6 + Avis HR positif  → Plan de Formation
        - score_hse <  6 + Avis HR négatif  → Période d'essai non concluante
        """
        self._require_qcm_done('hse', "Évaluation HSE")
        if self.score_hse >= 6.0:
            self.state = 'presentation'
            self.hr_opinion = False
        else:
            opinion = self._require_hr_opinion(
                f"Score HSE = {self.score_hse}/10 (< 6). "
                "Veuillez saisir l'avis RH avant de continuer."
            )
            if opinion == 'negative':
                self.state = 'periode_essai_non_concluante'
            else:
                self.state = 'plan_formation'

    def _gate_evaluation_immersion(self):
        """
        Gate after Évaluation Immersion (operators only).
        - score_immersion >= 6  → Validé
        - score_immersion <  6 + Avis HR positif  → Plan de Formation
        - score_immersion <  6 + Avis HR négatif  → Période d'essai non concluante
        """
        self._require_qcm_done('immersion', "Évaluation Immersion")
        if self.score_immersion >= 6.0:
            self.state = 'valide'
            self.hr_opinion = False
        else:
            opinion = self._require_hr_opinion(
                f"Score Immersion = {self.score_immersion}/10 (< 6). "
                "Veuillez saisir l'avis RH avant de continuer."
            )
            if opinion == 'negative':
                self.state = 'periode_essai_non_concluante'
            else:
                self.state = 'plan_formation'

    # ─────────────────────────────────────────────────────────────────────────
    # Guard helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _require_qcm_done(self, qcm_type: str, stage_label: str):
        """Assert that at least one QCM session of the given type is completed."""
        done = self.qcm_session_ids.filtered(
            lambda s: s.qcm_type == qcm_type and s.state == 'done'
        )
        if not done:
            raise UserError(
                f"Aucune session QCM de type « {stage_label} » n'a encore été "
                "complétée pour ce plan. Veuillez d'abord soumettre le QCM."
            )

    def _require_hr_opinion(self, message: str) -> str:
        """Assert hr_opinion is set and return its value."""
        if not self.hr_opinion:
            raise UserError(message)
        return self.hr_opinion


# ── Module-level helper ───────────────────────────────────────────────────────

def _latest_score(sessions, qcm_type: str) -> float:
    """Return the score from the most recent done session of a given type."""
    typed = sessions.filtered(lambda s: s.qcm_type == qcm_type)
    if not typed:
        return 0.0
    latest = typed.sorted('date_end', reverse=True)[0]
    return latest.score
