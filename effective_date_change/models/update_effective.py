from odoo import models, fields
from odoo.exceptions import UserError
from datetime import date
from datetime import datetime

class UpdateEffective(models.Model):
    _inherit = "stock.picking"

    date_of_transfer = fields.Datetime(string="Effective Date", default=False, states={
        'draft': [('invisible', False)],
        'waiting': [('invisible', False)],
        'ready': [('invisible', False)],
        'done': [('invisible', True)],
    })

    def wiz_open(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'change.effective.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    # Overriding tombol validate dengan fungsi tambahan
    # Yang memungkinkan untuk mengganti tanggal effective date
    def button_validate(self):
        res = super(UpdateEffective, self).button_validate()

        # Jika tanggal transfer kosong, maka skip kode perhitungan di bawah
        # dan gunakan perhitungan normal default milik Odoo.
        if self.date_of_transfer != False:

            # Mengganti date_done (Effective Date)
            if self.date_of_transfer != False:
                selected_date = self.date_of_transfer
            else:
                selected_date = datetime.now()

            self.date_done = selected_date

            # Mengganti tanggal stock.valuation.layer
            self.env.cr.execute("UPDATE stock_valuation_layer SET create_date = (%s) WHERE description LIKE (%s)", [selected_date, str(self.name + "%")])

            # Mengganti tanggal stock.move.line
            for stock_move_line in self.env['stock.move.line'].search([('reference', 'ilike', str(self.name + "%"))]):
                stock_move_line.date = selected_date

            # Mengganti tanggal stock.move
            for stock_move in self.env['stock.move'].search([('reference', 'ilike', str(self.name + "%"))]):
                stock_move.date = selected_date

            # Mengganti tanggal account.move.line
            self.env.cr.execute("UPDATE account_move_line SET date = (%s) WHERE ref SIMILAR TO %s", [selected_date, str(self.name + "%")])

            # Mengganti tanggal stock.move
            for stock_move in self.env['stock.move'].search([('reference', 'ilike', str(self.name + "%"))]):
                stock_move.date = selected_date

            # Mengganti tanggal account.move
            self.env.cr.execute("UPDATE account_move set date = (%s) WHERE ref SIMILAR TO %s", [selected_date, str(self.name + "%")])

            # Mengambil Currency System ID
            system_default_currency = int(self.env.ref('base.main_company').currency_id)
            current_picking_id = self.picking_type_id.code
            purchase_orders_ids = self.env['purchase.order'].search([('name', '=', str(self.origin))])

            # Jika PO picking merupakan incoming transfer serta Purchase Order menggunakan currency asing
            # Maka lakukan perhitungan ulang valuasi
            if current_picking_id == 'internal':
                pass
            elif current_picking_id == 'outgoing':
                pass
            elif current_picking_id == 'incoming':
                try:
                    if current_picking_id == 'incoming' and int(purchase_orders_ids.currency_id) != system_default_currency:
                        inverse_rate = float(self.env['res.currency.rate'].search([('currency_id', '=', int(purchase_orders_ids.currency_id)), ('name', '=', selected_date.strftime('%Y-%m-%d'))]).inverse_company_rate)
                        if inverse_rate == 0.0:
                            raise UserError('You have selected the currency rate of ' + str(
                                purchase_orders_ids.currency_id.name) + ' which is currently not available based on your selected date. Make sure to fill it under Accounting > Settings > Currencies > ' + str(
                                purchase_orders_ids.currency_id.name) + '!')
                        else:
                            po_quantity = []
                            po_price_unit = []
                            po_tax_include = []
                            po_tax_amount = []
                            po_subtotal = []

                            for product in self.env['purchase.order.line'].search([('order_id', '=', int(purchase_orders_ids))]):
                                po_quantity.append(product.product_qty)
                                po_price_unit.append(product.price_unit)
                                po_tax_include.append(product.taxes_id.price_include)
                                po_tax_amount.append(product.price_tax)
                                po_subtotal.append(product.price_subtotal)

                            price_unit = []
                            counter = 0
                            for id in po_quantity:
                                if po_tax_include[counter] == True:
                                    unit_value = (float(po_quantity[counter]) * float(po_price_unit[counter]) - float(po_tax_amount[counter])) * float(inverse_rate)
                                    price_unit.append(float(unit_value))
                                else:
                                    unit_value = float(inverse_rate) * float(po_price_unit[counter]) * po_quantity[counter]
                                    price_unit.append(float(unit_value))
                                counter += 1

                            # Menghitung stock.valuation.layer
                            counter = 0
                            for product in self.env['stock.valuation.layer'].search([('description', 'ilike', str(self.name + "%"))]):
                                product.unit_cost = price_unit[counter] / product.quantity
                                product.value = product.unit_cost * product.quantity
                                counter += 1

                            # Menghitung account.move
                            account_move_ids = []
                            account_move_search = self.env['account.move'].search([('ref', 'like', str(self.name + "%"))])
                            for item in account_move_search:
                                account_move_ids.append((int(item.id)))

                            journal_entry = sorted(account_move_ids)

                            account_move_line = []
                            debit = []
                            credit = []

                            for journal_id in journal_entry:
                                for item in self.env['account.move.line'].search([('move_id', '=', journal_id)]):
                                    account_move_line.append(int(item.id))
                                    debit.append(int(item.debit))
                                    credit.append(int(item.credit))

                            account_move_lines = [account_move_line[i:i + 2] for i in range(0, len(account_move_line), 2)]

                            counter = 0
                            for record in account_move_lines:
                                debit = float(abs(price_unit[counter]))
                                self.env['account.move.line'].search([('id', '=', int(record[1]))]).with_context(check_move_validity=False).write({'debit': debit})

                                credit = float(abs(price_unit[counter]))
                                self.env['account.move.line'].search([('id', '=', int(record[0]))]).with_context(check_move_validity=False).write({'credit': credit})

                                counter += 1
                except:
                    pass
            else:
                pass

                def update_journal_name(selected_prefix, picking_name):
                    already_created_sequence_prefix = self.env['account.move'].search([('sequence_prefix', '=', str(selected_prefix))])
                    seq_numbers = [account_move.sequence_number for account_move in already_created_sequence_prefix]
                    max_sequence_number = max(seq_numbers, default=0) + 1

                    for journal_entries in self.env['account.move'].search([('ref', 'like', picking_name)]):
                        new_name = selected_prefix + str(max_sequence_number).zfill(4)
                        self.env.cr.execute("UPDATE account_move SET name = (%s) WHERE id = %s", [new_name, int(journal_entries.id)])
                        journal_entries.sequence_number = max_sequence_number
                        journal_entries.sequence_prefix = selected_prefix

                        for invoice_line_ids in journal_entries.invoice_line_ids:
                            invoice_line_ids.move_name = new_name

                        max_sequence_number += 1

                # Mengambil nama journal serta menentukan tanggal dan tahun dari tanggal yang dipilih
                account_move = self.env['account.move'].search([('ref', 'ilike', str(self.name))])
                account_move_short_code = account_move.journal_id.code or self.env["account.journal"].search([('name', '=', 'Inventory Valuation')]).code
                selected_year = selected_date.strftime("%Y")
                selected_month = selected_date.strftime("%m")

                currentMonth = datetime.now().month
                currentYear = datetime.now().year

                # Jika bulan dan tahun terpilih sama dengan bulan dan tahun saat ini, maka penggantian nama tidak dilakukan
                # hal tersebut karena bertubrukan dengan system sequencing accounting
                # sehingga tanggal yang bisa di backdate adalah tanggal yang berbeda dengan bulan sekarang saja
                if int(selected_month) == currentMonth and int(selected_year) == currentYear:
                    pass
                else:
                    if account_move_short_code != False:
                        # Forming nama journal entry baru
                        selected_prefix = str(account_move_short_code + "/" + selected_year + "/" + selected_month + "/")
                        collected_name = []  # Simply put query recursion into list for performance
                        for created_journals in self.env['account.move'].search([('name', 'like', str(selected_prefix))]):
                            collected_name.append(created_journals.name)

                        picking_name = str(self.name)
                        if selected_year == date.today().year and selected_month == date.today().month:
                            pass
                        else:
                            update_journal_name(selected_prefix, picking_name)
                    else:
                        pass
        else:
            pass

        return res