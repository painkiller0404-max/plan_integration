"""
QCM Kiosk Controller — tablet interface for the integration plan.

Two-phase flow:
  Phase 1  /qcm/kiosk          (auth=user  — HR is logged in)
           /qcm/kiosk/start    (auth=user  — HR creates session)

  Phase 2  /qcm/take/<token>          (auth=public — employee test)
           /qcm/take/<token>/submit   (auth=public — employee submits)
"""
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Mirrors the model constant — which stage creates which QCM type
STAGE_QCM_MAP = {
    'culture_valeurs':      'rh',
    'evaluation_hse':       'hse',
    'evaluation_immersion': 'immersion',
}


class QcmKioskController(http.Controller):

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 1 — HR kiosk selection (requires Odoo login)
    # ─────────────────────────────────────────────────────────────────────────

    @http.route('/qcm/kiosk', auth='user', methods=['GET'], website=False)
    def kiosk_select(self, error=None, plan_id=None, **kwargs):
        """
        HR selection page: choose an integration plan, then pick one of its
        pending (draft) QCM sessions to start.  No new session is created.
        """
        env = request.env
        # Non-terminal plans that have at least one draft session
        plans = env['integration.plan'].search(
            [('is_terminal', '=', False)],
            order='hire_date desc, name'
        )
        selected_plan = None
        draft_sessions = request.env['integration.qcm.session'].sudo().browse()
        if plan_id:
            try:
                selected_plan = env['integration.plan'].browse(int(plan_id))
                if selected_plan.exists():
                    # Only show the session(s) for the CURRENT stage
                    expected_type = STAGE_QCM_MAP.get(selected_plan.state)
                    if expected_type:
                        draft_sessions = selected_plan.qcm_session_ids.filtered(
                            lambda s: s.state == 'draft'
                            and s.qcm_type == expected_type
                        )
                    # If the plan is not at a QCM stage, draft_sessions stays empty
            except (ValueError, TypeError):
                pass

        return request.render('plan_integration.qcm_kiosk_select', {
            'plans': plans,
            'selected_plan': selected_plan,
            'draft_sessions': draft_sessions,
            'error': error or kwargs.get('error'),
        })

    @http.route('/qcm/kiosk/start', auth='user', methods=['POST'],
                website=False, csrf=False)
    def kiosk_start(self, **post):
        """
        HR submits: start an existing draft session and redirect to the test.
        We start the session (creating response rows) then redirect to the
        public test page so the employee does not need an Odoo account.
        """
        session_id_str = post.get('session_id', '').strip()
        plan_id_str    = post.get('plan_id',    '').strip()

        if not session_id_str:
            err = 'missing_session'
            suffix = f'?plan_id={plan_id_str}&error={err}' if plan_id_str else f'?error={err}'
            return request.redirect(f'/qcm/kiosk{suffix}', local=True)

        try:
            session_id = int(session_id_str)
        except ValueError:
            return request.redirect('/qcm/kiosk?error=invalid', local=True)

        env = request.env
        session = env['integration.qcm.session'].browse(session_id)

        if not session.exists():
            return request.redirect('/qcm/kiosk?error=notfound', local=True)
        if session.state != 'draft':
            return request.redirect(
                f'/qcm/kiosk?plan_id={session.plan_id.id}&error=already_started',
                local=True
            )
        if not session.qcm_id.question_ids:
            return request.redirect(
                f'/qcm/kiosk?plan_id={session.plan_id.id}&error=no_questions',
                local=True
            )

        # Start the session (creates response rows, marks in_progress)
        session._action_start_portal()

        # Redirect to the public test page
        return request.redirect(f'/qcm/take/{session.token}', local=True)


    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 2 — Employee test page (public — no Odoo login required)
    # ─────────────────────────────────────────────────────────────────────────

    @http.route('/qcm/take/<string:token>', auth='public', methods=['GET'],
                website=False, csrf=False, save_session=False)
    def take_test(self, token, error=None, **kwargs):
        """
        Clean tablet test form shown to the employee.
        No Odoo menus, no score fields, no extra buttons.
        """
        session = request.env['integration.qcm.session'].sudo().search(
            [('token', '=', token)], limit=1
        )
        if not session:
            return request.render(
                'plan_integration.qcm_portal_not_found', {}, status=404
            )
        if session.state == 'done':
            return request.render(
                'plan_integration.qcm_portal_done', {'session': session}
            )
        return request.render(
            'plan_integration.qcm_portal_test',
            {'session': session, 'error': error or kwargs.get('error')}
        )

    @http.route('/qcm/take/<string:token>/submit', auth='public', methods=['POST'],
                website=False, csrf=False, save_session=False)
    def take_test_submit(self, token, **post):
        """Process the employee's submitted answers."""
        session = request.env['integration.qcm.session'].sudo().search(
            [('token', '=', token)], limit=1
        )
        if not session or session.state != 'in_progress':
            return request.redirect(f'/qcm/take/{token}', local=True)

        # Save selected answers (form fields named  answer_<response_id>)
        for response in session.response_ids:
            raw = post.get(f'answer_{response.id}')
            if raw:
                try:
                    response.selected_answer_id = int(raw)
                except (ValueError, TypeError):
                    _logger.warning(
                        "Invalid answer value '%s' for response %s", raw, response.id
                    )

        # Guard: all questions must be answered
        unanswered = session.response_ids.filtered(lambda r: not r.selected_answer_id)
        if unanswered:
            return request.redirect(
                f'/qcm/take/{token}?error={len(unanswered)}', local=True
            )

        try:
            session.action_submit()
        except Exception:
            _logger.exception("Error submitting session %s", session.id)
            return request.redirect(f'/qcm/take/{token}?error=submit', local=True)

        return request.redirect(f'/qcm/take/{token}', local=True)
