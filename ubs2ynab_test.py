import datetime
import os
import ubs2ynab
import unittest

from abc import ABC
from parameterized import parameterized
from pathlib import Path
from unittest.mock import patch, MagicMock
from ynab.models import TransactionClearedStatus

TESTDATA_DIR = os.path.join(Path(__file__).parent, 'testdata')


class YnabTestCase(unittest.TestCase, ABC):

    def setUp(self):
        # Mock YNAB API
        self.mock_transactions_api = MagicMock()
        patch('ynab.TransactionsApi',
              return_value=self.mock_transactions_api).start()

        self.mock_api_client = MagicMock()

    def tearDown(self):
        patch.stopall()

    def _get_transaction_arguments(self, account_id=None):
        args, _ = self.mock_transactions_api.create_transaction.call_args
        post_transaction_wrapper = args[1]
        return [t for t in post_transaction_wrapper.transactions if account_id is None or t.account_id == account_id]


class ImportCsvLineTestCase(YnabTestCase, ABC):

    def setUp(self):
        super().setUp()

        self.mock_csv_dict_reader = patch('csv.DictReader').start()

        # Mock open() to prevent actual file I/O during tests
        patch('builtins.open').start()


class ImportCreditCsvTestCase(ImportCsvLineTestCase):

    def _good_csv_response(self,
                           account_number='ACC1',
                           purchase_date='13.01.2000',
                           booking_text='Test payee',
                           credit='',
                           debit='',
                           amount='100.00'):
        return {
            'Account number': account_number,
            'Purchase date': purchase_date,
            'Booking text': booking_text,
            'Credit': credit,
            'Debit': debit,
            'Amount': amount
        }

    def test_import_calls_api(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response()]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        ts = self._get_transaction_arguments()
        self.assertEqual(len(ts), 1)

    def test_dry_run_import_doesnt_call_api(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response()]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=True)

        self.mock_transactions_api.create_transaction.assert_not_called()

    def test_purchase_date_is_read(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            purchase_date='12.07.2025')]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.var_date, datetime.date(2025, 7, 12))

    def test_booking_text_is_read(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            booking_text='Some payee')]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.payee_name, 'Some payee')

    def test_credit_amount_takes_presedence_over_just_amount(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            credit='150.00',
            amount='100.00')  # Deliberately different from credit to ensure credit is used
        ]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.amount, 150000)

    def test_credit_amount_is_cleared(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            credit='150.00')]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.cleared, TransactionClearedStatus.CLEARED)

    def test_debit_amount_takes_presedence_over_just_amount(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            debit='150.00',
            amount='100.00')  # Deliberately different from debit to ensure debit is used
        ]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.amount, -150000)

    def test_debit_amount_is_cleared(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            debit='150.00')]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.cleared, TransactionClearedStatus.CLEARED)

    def test_just_amount_without_transfer_treated_as_debit(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            amount='150.00',
            booking_text='Some payee not denoting a transfer')]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.amount, -150000)

    def test_just_amount_with_transfer_treated_as_credit(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            amount='150.00',
            booking_text='TRANSFER FROM ACCOUNT')]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.amount, 150000)

    def test_just_amount_is_not_cleared(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            amount='150.00')]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.cleared, TransactionClearedStatus.UNCLEARED)

    def test_import_id_is_correct(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            purchase_date='01.01.2025',
            amount='100.00'
        )]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.import_id, 'UBS2YNAB:-100000:2025-01-01:0')

    def test_import_id_ordinal_is_desc(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            booking_text='First'), self._good_csv_response(booking_text='Second')]

        ubs2ynab.importCreditCsv('irrelevant.csv', 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        payees = [t.payee_name for t in self._get_transaction_arguments()]
        ordinals = [t.import_id.split(':')[-1]
                    for t in self._get_transaction_arguments()]
        self.assertEqual(payees, ['First', 'Second'])
        self.assertEqual(ordinals, ['1', '0'])


class ImportDebitCsvTestCase(ImportCsvLineTestCase):

    def _good_csv_response(self,
                           trade_date='2000-01-13',
                           description1='Test payee',
                           credit='1.00',
                           debit='',
                           ):
        return {
            'Trade date': trade_date,
            'Description1': description1,
            'Credit': credit,
            'Debit': debit
        }

    def test_import_calls_api(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response()]

        ubs2ynab.importDebitCsv('irrelevant.csv', 'some_budget_id',
                                'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        ts = self._get_transaction_arguments()
        self.assertEqual(len(ts), 1)

    def test_dry_run_import_doesnt_call_api(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response()]

        ubs2ynab.importDebitCsv('irrelevant.csv', 'some_budget_id',
                                'some_account_id', self.mock_api_client, dry_run=True)

        self.mock_transactions_api.create_transaction.assert_not_called()

    def test_trade_date_is_read(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            trade_date='2025-07-12')]

        ubs2ynab.importDebitCsv('irrelevant.csv', 'some_budget_id',
                                'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.var_date, datetime.date(2025, 7, 12))

    def test_description1_is_read(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            description1='Some payee')]

        ubs2ynab.importDebitCsv('irrelevant.csv', 'some_budget_id',
                                'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.payee_name, 'Some payee')

    def test_credit_amount_takes_presedence_over_debit_amount(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            credit='150.00',
            debit='100.00')  # Deliberately different from credit to ensure credit is used
        ]

        ubs2ynab.importDebitCsv('irrelevant.csv', 'some_budget_id',
                                'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.amount, 150000)

    def test_transaction_is_cleared(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response()]

        ubs2ynab.importDebitCsv('irrelevant.csv', 'some_budget_id',
                                'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.cleared, TransactionClearedStatus.CLEARED)

    def test_import_id_is_correct(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            trade_date='2025-01-01',
            credit='100.00'
        )]

        ubs2ynab.importDebitCsv('irrelevant.csv', 'some_budget_id',
                                'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.import_id, 'UBS2YNAB:100000:2025-01-01:0')

    def test_import_id_ordinal_is_desc(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            description1='First'), self._good_csv_response(description1='Second')]

        ubs2ynab.importDebitCsv('irrelevant.csv', 'some_budget_id',
                                'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        payees = [t.payee_name for t in self._get_transaction_arguments()]
        ordinals = [t.import_id.split(':')[-1]
                    for t in self._get_transaction_arguments()]
        self.assertEqual(payees, ['First', 'Second'])
        self.assertEqual(ordinals, ['1', '0'])


class ImportRevolutCsvTestCase(ImportCsvLineTestCase):

    def _good_csv_response(self,
                           type='Card Payment',
                           product='Current',
                           started_date='2020-01-13 19:20:21',
                           description='Test payee',
                           amount='-50.00',
                           fee='0.00',
                           state='COMPLETED',
                           ):
        return {
            'Type': type,
            'Product': product,
            'Started Date': started_date,
            'Description': description,
            'Amount': amount,
            'Fee': fee,
            'State': state,
        }

    def test_import_calls_api(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response()]

        ubs2ynab.importRevolutCsv('irrelevant.csv', 'some_budget_id',
                                  'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        ts = self._get_transaction_arguments()
        self.assertEqual(len(ts), 1)

    def test_dry_run_import_doesnt_call_api(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response()]

        ubs2ynab.importRevolutCsv('irrelevant.csv', 'some_budget_id',
                                  'some_account_id', self.mock_api_client, dry_run=True)

        self.mock_transactions_api.create_transaction.assert_not_called()

    @parameterized.expand([
        ('Savings',),
        ('Made-up product'),
    ])
    def test_non_current_products_are_ignored(self, product):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            product=product)]

        ubs2ynab.importRevolutCsv('irrelevant.csv', 'some_budget_id',
                                  'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        ts = self._get_transaction_arguments()
        self.assertEqual(len(ts), 0)

    @parameterized.expand([
        ('To pocket CHF For a rainy day',),
        ('Balance migration to another region or legal entity',),
    ])
    def test_specific_transfers_are_ignored(self, ignored_description):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(type='Transfer',
                                                                          description=ignored_description)]

        ubs2ynab.importRevolutCsv('irrelevant.csv', 'some_budget_id',
                                  'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        ts = self._get_transaction_arguments()
        self.assertFalse(ts)

    def test_started_date_is_read(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            started_date='2025-04-01 11:53:59')]

        ubs2ynab.importRevolutCsv('irrelevant.csv', 'some_budget_id',
                                  'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.var_date, datetime.date(2025, 4, 1))

    def test_description_is_read(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            description='Some payee')]

        ubs2ynab.importRevolutCsv('irrelevant.csv', 'some_budget_id',
                                  'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.payee_name, 'Some payee')

    def test_fee_is_deducted_from_amount(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            amount='-50.00',
            fee='2.00')]

        ubs2ynab.importRevolutCsv('irrelevant.csv', 'some_budget_id',
                                  'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.amount, -52000)  # YNAB amounts are in milliunits

    def test_completed_row_is_cleared(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            state='COMPLETED')]

        ubs2ynab.importRevolutCsv('irrelevant.csv', 'some_budget_id',
                                  'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.cleared, TransactionClearedStatus.CLEARED)

    @parameterized.expand([
        ('PENDING',),
        ('Made-up state'),
    ])
    def test_non_completed_row_is_not_cleared(self, state):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            state=state)]

        ubs2ynab.importRevolutCsv('irrelevant.csv', 'some_budget_id',
                                  'some_account_id', self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.cleared, TransactionClearedStatus.UNCLEARED)

    def test_import_id_is_correct(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            started_date='2025-01-01 11:53:59',
            amount='-51.23'
        )]

        ubs2ynab.importRevolutCsv('irrelevant.csv', 'some_budget_id',
                                  'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.import_id, 'UBS2YNAB:-51230:2025-01-01:0')

    def test_import_id_ordinal_is_asc(self):
        self.mock_csv_dict_reader.return_value = [self._good_csv_response(
            description='First'), self._good_csv_response(description='Second')]

        ubs2ynab.importRevolutCsv('irrelevant.csv', 'some_budget_id',
                                  'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        payees = [t.payee_name for t in self._get_transaction_arguments()]
        ordinals = [t.import_id.split(':')[-1]
                    for t in self._get_transaction_arguments()]
        self.assertEqual(payees, ['Second', 'First'])
        self.assertEqual(ordinals, ['1', '0'])


class FileImportTestCase(YnabTestCase):
    """Integration tests with full example files."""

    def test_full_ubs_credit_file(self):
        csv_path = os.path.join(TESTDATA_DIR, 'ubs_credit_card.csv')

        ubs2ynab.importCreditCsv(csv_path, 'some_budget_id',
                                 'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        import_ids = [t.import_id for t in self._get_transaction_arguments()]
        self.assertEqual(import_ids, ['UBS2YNAB:-24450:2025-09-16:0',
                                      'UBS2YNAB:-37900:2025-09-16:0',
                                      'UBS2YNAB:-2000:2025-09-15:0',
                                      'UBS2YNAB:-72750:2025-09-14:0',
                                      'UBS2YNAB:-16300:2025-09-13:0',
                                      'UBS2YNAB:-66950:2025-09-13:0',
                                      'UBS2YNAB:-11020:2025-09-12:0',
                                      'UBS2YNAB:600000:2025-09-12:0'])

    def test_full_ubs_debit_file(self):
        csv_path = os.path.join(TESTDATA_DIR, 'ubs_debit_card.csv')

        ubs2ynab.importDebitCsv(csv_path, 'some_budget_id',
                                'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        import_ids = [t.import_id for t in self._get_transaction_arguments()]
        self.assertEqual(import_ids, ['UBS2YNAB:-49950:2025-07-14:0',
                                      'UBS2YNAB:-98000:2025-07-13:0',
                                      'UBS2YNAB:-35000:2025-07-11:0',
                                      'UBS2YNAB:-216000:2025-07-09:0',
                                      'UBS2YNAB:-144000:2025-07-09:0',
                                      'UBS2YNAB:-161800:2025-07-07:0',
                                      'UBS2YNAB:-51590:2025-07-06:0'])

    def test_full_revolut_file(self):
        csv_path = os.path.join(TESTDATA_DIR, 'revolut.csv')

        ubs2ynab.importRevolutCsv(csv_path, 'some_budget_id',
                                  'some_account_id', self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        import_ids = [t.import_id for t in self._get_transaction_arguments()]
        self.assertEqual(import_ids, ['UBS2YNAB:-20260:2025-08-30:0',
                                      'UBS2YNAB:-11360:2025-08-30:0',
                                      'UBS2YNAB:-20000:2025-08-28:0',
                                      'UBS2YNAB:-364500:2025-08-27:0',
                                      'UBS2YNAB:500000:2025-08-26:0',
                                      'UBS2YNAB:-4970:2025-08-24:0',
                                      'UBS2YNAB:-29000:2025-08-25:0',
                                      'UBS2YNAB:4970:2025-08-24:0',
                                      'UBS2YNAB:-4059:2025-08-22:0',
                                      'UBS2YNAB:-20000:2025-08-20:0',
                                      'UBS2YNAB:-37650:2025-08-17:0',
                                      'UBS2YNAB:-20000:2025-08-17:0',
                                      'UBS2YNAB:-20000:2025-08-14:0',
                                      'UBS2YNAB:-70750:2025-08-11:0',
                                      'UBS2YNAB:-4400:2025-08-08:0',
                                      'UBS2YNAB:-15000:2025-08-08:0',
                                      'UBS2YNAB:-20000:2025-08-04:0',
                                      'UBS2YNAB:-9410:2025-08-02:0',
                                      'UBS2YNAB:-820:2025-08-01:0',
                                      'UBS2YNAB:-44060:2025-07-30:0'])


class UbsEmailHelper:

    def mock_email(self, html, date=datetime.datetime(2025, 1, 2, 10, 0, 0)):
        m = MagicMock()
        m.date = date
        m.html = html
        return m

    def good_notification(self, notification_text='Some notification', date=datetime.datetime(2025, 1, 2, 10, 0, 0)):
        return self.mock_email(f'<!-- NOTIFICATION_CONTENT_BEGIN -->\n{notification_text}\n<!-- NOTIFICATION_CONTENT_END -->', date)


class UbsCrediCardEmailHelper():

    def __init__(self, ubs: UbsEmailHelper):
        self.ubs = ubs

    def good_debit_notification(self, card_alias='1234', amount='56.78', payee='PAYEE', available_amount='1234.56', date=datetime.datetime(2025, 1, 2, 10, 0, 0)):
        notification_text = f'CHF {amount} have been charged to card "{card_alias}". {payee}. Available amount: CHF {available_amount}'
        return self.ubs.good_notification(notification_text, date)

    def good_credit_notification(self, card_alias='1234', available_amount='1234.56', date=datetime.datetime(2025, 1, 2, 10, 0, 0)):
        notification_text = f'Amount available on card "{card_alias}": CHF  {available_amount}.'
        return self.ubs.good_notification(notification_text, date)


class UbsDebitCardEmailHelper():

    def __init__(self, ubs: UbsEmailHelper):
        self.ubs = ubs

    def good_debit_notification(self, account_alias='Checking', amount='56.78', available_amount='1234.56', date=datetime.datetime(2025, 1, 2, 10, 0, 0)):
        notification_test = f'''Your account "{account_alias}" has been debited CHF {amount}.

The new account balance is CHF {available_amount}.

You are receiving this notification because you asked to be informed of your account transactions. You can adjust this in the settings of Digital Banking at any time.'''
        return self.ubs.good_notification(notification_test, date)

    def good_credit_notification(self, account_alias='Checking', amount='56.78', available_amount='1234.56', date=datetime.datetime(2025, 1, 2, 10, 0, 0)):
        notification_test = f'''Your account "{account_alias}" has been credited CHF {amount}.

The new account balance is CHF {available_amount}.

You are receiving this notification because you asked to be informed of your account transactions. You can adjust this in the settings of Digital Banking at any time.'''
        return self.ubs.good_notification(notification_test, date)


class importUbsFromEmailTestCase(YnabTestCase, ABC):

    def setUp(self):
        super().setUp()

        self.ubs = UbsEmailHelper()
        self.credit_card = UbsCrediCardEmailHelper(self.ubs)
        self.debit_card = UbsDebitCardEmailHelper(self.ubs)

        mock_mailbox_object = MagicMock()
        patch('ubs2ynab.MailBox', return_value=mock_mailbox_object).start()
        self.mock_mailbox = MagicMock()
        mock_mailbox_object.login.return_value.__enter__.return_value = self.mock_mailbox

    def tearDown(self):
        super().tearDown()
        patch.stopall()


class GeneralimportUbsFromEmailTestCase(importUbsFromEmailTestCase):

    def test_no_emails_doesnt_call_api(self):
        self.mock_mailbox.fetch.return_value = []
        account_map = {'1234': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_not_called()

    def test_non_ubs_email_doesnt_call_api(self):
        self.mock_mailbox.fetch.return_value = [
            self.ubs.mock_email('Some random email content')]
        account_map = {'1234': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_not_called()

    def test_debit_import_id_ordinal_is_asc(self):
        self.mock_mailbox.fetch.return_value = [self.credit_card.good_debit_notification(amount='12.34', card_alias='1234', payee='First'),
                                                self.debit_card.good_debit_notification(amount='12.34', account_alias='Acc')]
        account_map = {'1234': 'some_account_id',
                       'Acc': 'some_other_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        payees = [t.payee_name for t in self._get_transaction_arguments()]
        ordinals = [t.import_id.split(':')[-1]
                    for t in self._get_transaction_arguments()]
        # Debit card notification has no payee
        self.assertEqual(payees, [None, 'First'])
        self.assertEqual(ordinals, ['1', '0'])


class UbsCreditCardNotificationTestCase(importUbsFromEmailTestCase):

    def test_usb_email_calls_api(self):
        self.mock_mailbox.fetch.return_value = [
            self.credit_card.good_debit_notification(card_alias='1234')]
        account_map = {'1234': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        self.mock_transactions_api.create_transaction.assert_called_once()
        ts = self._get_transaction_arguments()
        self.assertEqual(len(ts), 1)

    def test_dry_run_import_doesnt_call_api(self):
        self.mock_mailbox.fetch.return_value = [
            self.credit_card.good_debit_notification(card_alias='1234')]
        account_map = {'1234': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=True)

        self.mock_transactions_api.create_transaction.assert_not_called()

    def test_debit_account_is_matched_by_card(self):
        msg = self.credit_card.good_debit_notification(card_alias='1234')
        self.mock_mailbox.fetch.return_value = [msg]
        account_map = {'1234': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.account_id, 'some_account_id')

    def test_debit_amount_is_negativ(self):
        msg = self.credit_card.good_debit_notification(
            card_alias='1234', amount='56.78')
        self.mock_mailbox.fetch.return_value = [msg]
        account_map = {'1234': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.amount, -56780)  # YNAB amounts are in milliunits

    def test_debit_date_is_read_from_email(self):
        msg = self.credit_card.good_debit_notification(
            card_alias='1234', date=datetime.datetime(2025, 3, 4, 15, 30, 0))
        self.mock_mailbox.fetch.return_value = [msg]
        account_map = {'1234': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.var_date, datetime.date(2025, 3, 4))

    def test_debit_payee_is_read(self):
        msg = self.credit_card.good_debit_notification(
            card_alias='1234', payee='Somemarkt AG')
        self.mock_mailbox.fetch.return_value = [msg]
        account_map = {'1234': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.payee_name, 'Somemarkt AG')

    def test_debit_import_id_is_correct(self):
        msg = self.credit_card.good_debit_notification(
            card_alias='1234', amount='51.23', date=datetime.datetime(2025, 3, 4, 15, 30, 0))
        self.mock_mailbox.fetch.return_value = [msg]
        account_map = {'1234': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.import_id, 'UBS2YNAB:-51230:2025-03-04:0')

    def test_lone_credit_email_is_ignored(self):
        self.mock_mailbox.fetch.return_value = [
            self.credit_card.good_credit_notification()]

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', {}, self.mock_api_client, dry_run=False)

        self.assertFalse(self._get_transaction_arguments())

    @parameterized.expand([1, 59, 120])
    def test_credit_email_with_random_email_seconds_after_is_ignored(self, seconds_after):
        date = datetime.datetime(2025, 1, 2, 10, 0, 0)
        self.mock_mailbox.fetch.return_value = [self.credit_card.good_credit_notification(card_alias='1234', date=date),
                                                self.ubs.good_notification(date=date + datetime.timedelta(seconds=seconds_after)),]
        account_map = {'1234': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        self.assertFalse(self._get_transaction_arguments('some_account_id'))

    @parameterized.expand([1, 59, 120])
    def test_credit_email_with_random_ubs_email_seconds_before_is_ignored(self, seconds_before):
        date = datetime.datetime(2025, 1, 2, 10, 0, 0)
        self.mock_mailbox.fetch.return_value = [self.ubs.good_notification(date=date - datetime.timedelta(seconds=seconds_before)),
                                                self.credit_card.good_credit_notification(card_alias='1234', date=date)]
        account_map = {'1234': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        self.assertFalse(self._get_transaction_arguments('some_account_id'))

    @parameterized.expand([1, 59])
    def test_credit_gets_amount_from_debit_email_after(self, seconds_after):
        date = datetime.datetime(2025, 1, 2, 10, 0, 0)
        self.mock_mailbox.fetch.return_value = [self.credit_card.good_credit_notification(card_alias='1234', date=date),
                                                self.debit_card.good_debit_notification(account_alias='Acc', amount='123.45', date=date + datetime.timedelta(seconds=seconds_after)),]
        account_map = {'1234': 'credit_account_id', 'Acc': 'debit_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments('credit_account_id')[0]
        self.assertEqual(t.amount, 123450)  # YNAB amounts are in milliunits

    def test_credit_not_created_when_debit_email_is_too_after(self):
        debit_card = UbsDebitCardNotificationTestCase()
        date = datetime.datetime(2025, 1, 2, 10, 0, 0)
        self.mock_mailbox.fetch.return_value = [self.credit_card.good_credit_notification(card_alias='1234', date=date),
                                                self.debit_card.good_debit_notification(account_alias='Acc', amount='123.45', date=date + datetime.timedelta(seconds=60)),]
        account_map = {'1234': 'credit_account_id', 'Acc': 'debit_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        self.assertFalse(self._get_transaction_arguments('credit_account_id'))

    @parameterized.expand([1, 59])
    def test_credit_gets_amount_from_debit_email_before(self, seconds_after):
        date = datetime.datetime(2025, 1, 2, 10, 0, 0)
        self.mock_mailbox.fetch.return_value = [self.debit_card.good_debit_notification(account_alias='Acc', amount='123.45', date=date - datetime.timedelta(seconds=seconds_after)),
                                                self.credit_card.good_credit_notification(card_alias='1234', date=date)]
        account_map = {'1234': 'credit_account_id', 'Acc': 'debit_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments('credit_account_id')[0]
        self.assertEqual(t.amount, 123450)  # YNAB amounts are in milliunits

    def test_credit_not_created_when_debit_email_is_too_before(self):
        date = datetime.datetime(2025, 1, 2, 10, 0, 0)
        self.mock_mailbox.fetch.return_value = [self.debit_card.good_debit_notification(account_alias='Acc', amount='123.45', date=date - datetime.timedelta(seconds=60)),
                                                self.credit_card.good_credit_notification(card_alias='1234', date=date)]
        account_map = {'1234': 'credit_account_id', 'Acc': 'debit_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        self.assertFalse(self._get_transaction_arguments('credit_account_id'))

    def test_credit_import_id_is_correct(self):
        date = datetime.datetime(2025, 1, 2, 10, 0, 0)
        self.mock_mailbox.fetch.return_value = [self.credit_card.good_credit_notification(card_alias='1234', date=date),
                                                self.debit_card.good_debit_notification(account_alias='Acc', amount='123.45', date=date + datetime.timedelta(seconds=1)),]
        account_map = {'1234': 'credit_account_id', 'Acc': 'debit_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments('credit_account_id')[0]
        self.assertEqual(t.import_id, 'UBS2YNAB:123450:2025-01-02:0')


class UbsDebitCardNotificationTestCase(importUbsFromEmailTestCase):

    @parameterized.expand(['credit', 'debit'])
    def test_account_is_matched_by_alias(self, kind):
        msg = self.debit_card.good_credit_notification(
            account_alias='Acc') if kind == 'credit' else self.debit_card.good_debit_notification(account_alias='Acc')
        self.mock_mailbox.fetch.return_value = [msg]
        account_map = {'Acc': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.account_id, 'some_account_id')

    @parameterized.expand(['credit', 'debit'])
    def test_date_is_read_from_email(self, kind):
        d = datetime.datetime(2025, 3, 4, 15, 30, 0)
        msg = self.debit_card.good_credit_notification(
            account_alias='Acc', date=d) if kind == 'credit' else self.debit_card.good_debit_notification(account_alias='Acc', date=d)
        self.mock_mailbox.fetch.return_value = [msg]
        account_map = {'Acc': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.var_date, datetime.date(2025, 3, 4))

    def test_debit_amount_is_negativ(self):
        msg = self.debit_card.good_debit_notification(
            account_alias='Acc', amount='12.34')
        self.mock_mailbox.fetch.return_value = [msg]
        account_map = {'Acc': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.amount, -12340)  # YNAB amounts are in milliunits

    def test_debit_import_id_is_correct(self):
        date = datetime.datetime(2025, 3, 4, 15, 30, 0)
        msg = self.debit_card.good_debit_notification(
            account_alias='Acc', amount='12.34', date=date)
        self.mock_mailbox.fetch.return_value = [msg]
        account_map = {'Acc': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.import_id, 'UBS2YNAB:-12340:2025-03-04:0')

    def test_credit_amount_is_positiv(self):
        msg = self.debit_card.good_credit_notification(
            account_alias='Acc', amount='12.34')
        self.mock_mailbox.fetch.return_value = [msg]
        account_map = {'Acc': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.amount, 12340)  # YNAB amounts are in milliunits

    def test_credit_import_id_is_correct(self):
        date = datetime.datetime(2025, 3, 4, 15, 30, 0)
        msg = self.debit_card.good_credit_notification(
            account_alias='Acc', amount='12.34', date=date)
        self.mock_mailbox.fetch.return_value = [msg]
        account_map = {'Acc': 'some_account_id'}

        ubs2ynab.importUbsFromEmail('some_server', 'some_email', 'some_password', 'some_mailbox',
                                    'some_budget_id', account_map, self.mock_api_client, dry_run=False)

        t = self._get_transaction_arguments()[0]
        self.assertEqual(t.import_id, 'UBS2YNAB:12340:2025-03-04:0')


if __name__ == '__main__':
    unittest.main()
