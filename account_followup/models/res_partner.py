# -*- coding: utf-8 -*-
# Copyright 2004-2010 Tiny SPRL (<http://tiny.be>)
# Copyright 2007 Tecnativa - Vicent Cubells
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openerp import api, fields, models, _
from openerp.exceptions import ValidationError
from lxml import etree


class ResPartner(models.Model):
    _inherit = "res.partner"

    payment_responsible_id = fields.Many2one(
        comodel_name='res.users',
        ondelete='set null',
        string='Follow-up Responsible',
        track_visibility="onchange",
        copy=False,
        help="Optionally you can assign a user to this field, which will "
             "make him responsible for the action.",
    )
    payment_note = fields.Text(
        string='Customer Payment Promise',
        help="Payment Note",
        track_visibility="onchange",
        copy=False,
    )
    payment_next_action = fields.Text(
        string='Next Action',
        copy=False,
        track_visibility="onchange",
        help="This is the next action to be taken.  It will automatically "
             "be set when the partner gets a follow-up level that requires "
             "a manual action. ",
    )
    payment_next_action_date = fields.Date(
        string='Next Action Date',
        copy=False,
        help="This is when the manual follow-up is needed. "
             "The date will be set to the current date when the partner "
             "gets a follow-up level that requires a manual action. "
             "Can be practical to set manually e.g. to see if he keeps "
             "his promises.",
    )
    unreconciled_aml_ids = fields.One2many(
        comodel_name='account.move.line',
        inverse_name='followup_id',
        string='partner_id',
        domain=[('reconciled', '=', False)],
    )
    latest_followup_date = fields.Date(
        string="Latest Follow-up Date",
        store=False,
        compute='_get_latest',
        help="Latest date that the follow-up level of the partner was changed",
    )
    latest_followup_level_id = fields.Many2one(
        comodel_name='account_followup.followup.line',
        string="Latest Follow-up Level",
        help="The maximum follow-up level",
        compute='_get_latest',
    )
    latest_followup_level_id_without_lit = fields.Many2one(
        comodel_name='account_followup.followup.line',
        string="Latest Follow-up Level without litigation",
        help="The maximum follow-up level without taking into account the "
             "account move lines with litigation",
        compute='_get_latest',
    )
    payment_amount_due = fields.Float(
        string="Amount Due",
        compute='_get_amounts_and_date',
    )
    payment_amount_overdue = fields.Float(
        string="Amount Overdue",
        compute='_get_amounts_and_date',
    )
    payment_earliest_due_date = fields.Date(
        string="Worst Due Date",
        compute='_get_amounts_and_date',
    )

    @api.model
    def fields_view_get(self, view_id=None, view_type=None, toolbar=False,
                        submenu=False):
        res = super(ResPartner, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar,
            submenu=submenu)
        if view_type == 'form' and self.env.context.get('Followupfirst'):
            doc = etree.XML(res['arch'], parser=None, base_url=None)
            first_node = doc.xpath("//page[@name='followup_tab']")
            root = first_node[0].getparent()
            root.insert(0, first_node[0])
            res['arch'] = etree.tostring(doc, encoding="utf-8")
        return res

    @api.multi
    @api.depends('latest_followup_date', 'latest_followup_level_id',
                 'latest_followup_level_id_without_lit')
    def _get_latest(self, company_id=None):
        res = {}
        company = self.company_id or self.env.user.company_id
        for partner in self:
            amls = partner.unreconciled_aml_ids
            latest_date = False
            latest_level = False
            latest_days = False
            latest_level_without_lit = False
            latest_days_without_lit = False
            for aml in amls:
                if (aml.company_id == company) and \
                        (aml.followup_line_id is not False) and \
                        (not latest_days or
                            latest_days < aml.followup_line_id.delay):
                    latest_days = aml.followup_line_id.delay
                    latest_level = aml.followup_line_id.id
                if (aml.company_id == company) and \
                        (not latest_date or latest_date < aml.followup_date):
                    latest_date = aml.followup_date
                if (aml.company_id == company) and \
                        (aml.blocked is False) and (
                            aml.followup_line_id is not False and (
                                not latest_days_without_lit or
                                latest_days_without_lit <
                                aml.followup_line_id.delay)):
                    latest_days_without_lit = aml.followup_line_id.delay
                    latest_level_without_lit = aml.followup_line_id.id
            res[partner.id] = {
                'latest_followup_date': latest_date,
                'latest_followup_level_id': latest_level,
                'latest_followup_level_id_without_lit':
                    latest_level_without_lit
            }
        return res

    @api.multi
    def do_partner_manual_action(self):
        # partner_ids -> res.partner
        for partner in self:
            # Check action: check if the action was not empty, if not add
            if partner.payment_next_action:
                action_text = (partner.payment_next_action or '') + "\n" + \
                              (partner.latest_followup_level_id_without_lit.
                               manual_action_note or '')
            else:
                action_text = \
                    partner.latest_followup_level_id_without_lit\
                    .manual_action_note or ''

            # Check date: only change when it did not exist already
            action_date = \
                partner.payment_next_action_date or \
                fields.date.context_today(self)

            # Check responsible: if partner has not got a responsible already,
            # take from follow-up
            responsible_id = False
            if partner.payment_responsible_id:
                responsible_id = partner.payment_responsible_id.id
            else:
                p = partner.latest_followup_level_id_without_lit. \
                    manual_action_responsible_id
                responsible_id = p and p.id or False
            partner.write({
                'payment_next_action_date': action_date,
                'payment_next_action': action_text,
                'payment_responsible_id': responsible_id
            })

    @api.multi
    def do_partner_print(self, wizard_partner_ids, data):
        # wizard_partner_ids are ids from special view, not from res.partner
        if not wizard_partner_ids:
            return {}
        data['partner_ids'] = wizard_partner_ids
        datas = {
            'ids': wizard_partner_ids,
            'model': 'account_followup.followup',
            'form': data
        }
        return self.env['report'].get_action(
            [], 'account_followup.report_followup', data=datas)

    @api.multi
    def do_partner_mail(self):
        # partner_ids are res.partner ids
        # If not defined by latest follow-up level, it will be the default
        # template if it can find it
        unknown_mails = 0
        for partner in self.with_context(followup=True):
            partners_to_email = \
                [child for child in partner.child_ids
                 if child.type == 'invoice' and child.email]
            if not partners_to_email and partner.email:
                partners_to_email = [partner]
            if partners_to_email:
                level = partner.latest_followup_level_id_without_lit
                for partner_to_email in partners_to_email:
                    if level and level.send_email and level.email_template_id \
                            and level.email_template_id.id:
                        level.email_template_id.send_mail(partner_to_email.id)
                    else:
                        mail_template_id = self.env.ref(
                            'account_followup.'
                            'email_template_account_followup_default')
                        mail_template_id.send_mail(partner_to_email.id)
                if partner not in partners_to_email:
                    self.message_post(
                        [partner.id],
                        body=_('Overdue email sent to %s' % ', '
                               .join(['%s <%s>' % (partner.name, partner.email)
                                      for partner in partners_to_email])))
            else:
                unknown_mails += 1
                action_text = _("Email not sent because of email address of "
                                "partner not filled in")
                if partner.payment_next_action_date:
                    payment_action_date = min(fields.date.context_today(self),
                                              partner.payment_next_action_date)
                else:
                    payment_action_date = fields.date.context_today(self)
                if partner.payment_next_action:
                    payment_next_action = \
                        partner.payment_next_action + " \n " + action_text
                else:
                    payment_next_action = action_text
                partner.write({
                    'payment_next_action_date': payment_action_date,
                    'payment_next_action': payment_next_action}
                )
        return unknown_mails

    @api.multi
    def get_followup_table_html(self):
        """ Build the html tables to be included in emails send to partners,
            when reminding them their overdue invoices.
            :param ids: [id] of the partner for whom we are building the tables
            :rtype: string
        """
        account_followup_print = self.env['account_followup.print']

        self.ensure_one()
        partner = self.commercial_partner_id
        # copy the context to not change global context. Overwrite it because
        # _() looks for the lang in local variable 'context'.
        # Set the language to use = the partner language
        followup_table = ''
        if partner.unreconciled_aml_ids:
            company = self.with_context(lang=partner.lang).env.user.company_id
            current_date = fields.date.context_today(
                self.with_context(lang=partner.lang))
            rml_parse = \
                account_followup_print.report_rappel("followup_rml_parser")
            final_res = rml_parse._lines_get_with_partner(partner, company.id)

            for currency_dict in final_res:
                currency = currency_dict.get(
                    'line', [
                        {'currency_id': company.currency_id}
                    ])[0]['currency_id']
                followup_table += '''
                <table border="2" width=100%%>
                <tr>
                    <td>''' + _("Invoice Date") + '''</td>
                    <td>''' + _("Description") + '''</td>
                    <td>''' + _("Reference") + '''</td>
                    <td>''' + _("Due Date") + '''</td>
                    <td>''' + _("Amount") + " (%s)" % \
                                            currency.symbol + '''</td>
                    <td>''' + _("Lit.") + '''</td>
                </tr>
                '''
                total = 0
                for aml in currency_dict['line']:
                    block = aml['blocked'] and 'X' or ' '
                    total += aml['balance']
                    strbegin = "<TD>"
                    strend = "</TD>"
                    date = aml['date_maturity'] or aml['date']
                    if date <= current_date and aml['balance'] > 0:
                        strbegin = "<TD><B>"
                        strend = "</B></TD>"
                    followup_table += "<TR>" + strbegin + str(aml['date']) + \
                                      strend + strbegin + aml['name'] + \
                                      strend + strbegin + (aml['ref'] or '') \
                                      + strend + strbegin + str(date) + \
                                      strend + strbegin + str(aml['balance']) \
                                      + strend + strbegin + block + strend \
                                      + "</TR>"

                total = reduce(lambda x, y: x+y['balance'],
                               currency_dict['line'], 0.00)

                total = rml_parse.formatLang(total, dp='Account',
                                             currency_obj=currency)
                followup_table += '''<tr> </tr>
                                </table>
                                <center>''' + _("Amount due") \
                                  + ''' : %s </center>''' % total
        return followup_table

    @api.multi
    def write(self, values):
        if values.get("payment_responsible_id", False):
            for part in self:
                if part.payment_responsible_id != \
                        values["payment_responsible_id"]:
                    # Find partner_id of user put as responsible
                    responsible_partner_id = self.env.user.partner_id.id
                    self.env["mail.thread"].message_post(
                        body=_(
                            "You became responsible to do the next action for "
                            "the payment follow-up of") + " <b><a href='#id=" +
                        str(
                            part.id) + "&view_type=form&model=res.partner'> " +
                        part.name + " </a></b>",
                        type='comment',
                        subtype="mail.mt_comment",
                        model='res.partner',
                        res_id=part.id,
                        partner_ids=[responsible_partner_id],
                    )
        return super(ResPartner, self).write(values)

    @api.multi
    def action_done(self):
        return self.write({
            'payment_next_action_date': False,
            'payment_next_action': '',
            'payment_responsible_id': False
        })

    @api.multi
    def do_button_print(self):
        company_id = self.env.user.company_id.id
        for partner in self:
            # search if the partner has accounting entries to print. If not,
            # it may not be present in the psql view the report is based on,
            # so we need to stop the user here.
            if not self.env['account.move.line'].search([
                ('partner_id', '=', partner.id),
                ('reconciled', '=', False),
                ('company_id', '=', company_id),
                    '|', ('date_maturity', '=', False),
                    ('date_maturity', '<=', fields.date.context_today(self))]):
                raise ValidationError(
                    _("The partner does not have any accounting entries to "
                      "print in the overdue report for the current company."))
            self.message_post(
                [partner.id],
                body=_('Printed overdue payments report'),
            )
            # build the id of this partner in the psql view. Could be replaced
            # by a search with
            # [('company_id', '=', company_id),('partner_id', '=', ids[0])]
            wizard_partner_ids = [partner.id * 10000 + company_id]
            followup_ids = self.env['account_followup.followup'].search(
                [('company_id', '=', company_id)])
            if not followup_ids:
                raise ValidationError(
                    _("There is no followup plan defined for the current "
                      "company."))
            data = {
                'date': fields.date.today(),
                'followup_id': followup_ids[0],
            }
            # call the print overdue report on this partner
            return self.do_partner_print(wizard_partner_ids, data)

    @api.multi
    @api.depends('payment_amount_due', 'payment_amount_overdue',
                 'payment_earliest_due_date')
    def _get_amounts_and_date(self):
        """ Function that computes values for the followup functional fields.
            Note that 'payment_amount_due' is similar to 'credit' field on
            res.partner except it filters on user's company.
        """
        res = {}
        company = self.env.user.company_id
        current_date = fields.Date.context_today(self)
        for partner in self:
            worst_due_date = False
            amount_due = amount_overdue = 0.0
            for aml in partner.unreconciled_aml_ids:
                if aml.company_id == company:
                    date_maturity = aml.date_maturity or aml.date
                    if not worst_due_date or date_maturity < worst_due_date:
                        worst_due_date = date_maturity
                    amount_due += aml.result
                    if date_maturity <= current_date:
                        amount_overdue += aml.result
            res[partner.id] = {
                'payment_amount_due': amount_due,
                'payment_amount_overdue': amount_overdue,
                'payment_earliest_due_date': worst_due_date
            }
        return res

    @api.model
    def _get_followup_overdue_query(self, args, overdue_only=False):
        """
        This function is used to build the query and arguments to use when
        making a search on functional fields
            * payment_amount_due
            * payment_amount_overdue
        Basically, the query is exactly the same except that for overdue there
        is an extra clause in the WHERE.

        :param args: arguments given to the search in the usual domain
            notation (list of tuples)
        :param overdue_only: option to add the extra argument to filter on
            overdue accounting entries or not
        :returns: a tuple with
            * the query to execute as first element
            * the arguments for the execution of this query
        :rtype: (string, [])
        """
        company_id = self.env.user.company_id.id
        having_where_clause = ' AND '.join(
            map(lambda x: '(SUM(bal2) %s %%s)' % (x[1]), args))
        having_values = [x[2] for x in args]
        query = self.env['account.move.line']._query_get()
        overdue_only_str = overdue_only and 'AND date_maturity <= NOW()' or ''
        return ("""
            SELECT pid AS partner_id, SUM(bal2)
            FROM (
                SELECT CASE WHEN bal IS NOT NULL THEN bal
                ELSE 0.0 END AS bal2, p.id as pid
                FROM (
                    SELECT (debit-credit) AS bal, partner_id
                    FROM account_move_line l
                    WHERE account_id IN(SELECT id FROM account_account)
                    %s
                    AND reconciled IS FALSE
                    AND company_id = %s
                    AND %s) AS l
                RIGHT JOIN res_partner p
                ON p.id = partner_id ) AS pl
                GROUP BY pid HAVING """ %
                (
                    overdue_only_str,
                    query,
                    having_where_clause,
                    [company_id] +
                    having_values
                ))
