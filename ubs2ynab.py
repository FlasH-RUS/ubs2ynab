import argparse
import csv
import logging
import re
import ynab

from collections import namedtuple
from datetime import datetime, timedelta
from imap_tools import MailBox, AND
from ynab.models import TransactionClearedStatus
from ynab.models.new_transaction import NewTransaction


MODE_IMPORT_CREDIT_CSV = 'import_credit_csv'
MODE_IMPORT_DEBIT_CSV = 'import_debit_csv'
MODE_IMPORT_REVOLUT_CSV = 'import_revolut_csv'
MODE_IMPORT_UBS_FROM_GMAIL = 'import_ubs_email_notifications'

UBS_NOTIFICATION_REGEXP = '<!-- NOTIFICATION_CONTENT_BEGIN -->(.*)<!-- NOTIFICATION_CONTENT_END -->'
UBS_CREDIT_CARD_OUTFLOW_REGEXP = r'^CHF ([\d’]+\.\d\d) have been charged to card "(\d\d\d\d)"\. (.+)\. Available amount:'
UBS_CREDIT_CARD_INFLOW_REGEXP = r'^Amount available on card "(\d\d\d\d)": CHF'
UBS_DEBIT_CARD_REGEXP = r'^Your account "(.+)" has been (debited|credited) CHF ([\d’]+\.\d\d)\.'

# Maximum time between an outflow notification from a debit account and an inflow notification to a credit card
MAX_CREDIT_CARD_TRANSFT_TIMEDELTA = timedelta(minutes=1)

DAYS_TO_FETCH_EMAILS = 1


def _populateImportIds(transactions: list[NewTransaction]):
    """Populates `import_id` in the provided list of transactions.

    `import_id` format: "UBS2YNAB:$AMOUNT:$DATE:$ORDINAL" where:
    * $AMOUNT is the transaction amount in milliunits
    * $DATE is transaction date in ISO format
    * $ORDINAL is the 0-based ordinal within all transactions at the same date with the same amount

    Example: `UBS2YNAB:100000:2025-01-01:0`

    The assumption is that transactions are ordered exactly as in the UBS CSV (new-to-old).
    """
    for t in transactions:
        if not t.import_id:
            same_date_amount_indicies = [index for (index, item) in enumerate(
                transactions) if (item.var_date == t.var_date and item.amount == t.amount)]
            # Reverse the order as it's new-to-old in the original list and we need old-to-new for ordinals
            same_date_amount_indicies.reverse()
            for (ordinal, t_index) in enumerate(same_date_amount_indicies):
                other_t = transactions[t_index]
                other_t.import_id = f'UBS2YNAB:{other_t.amount}:{other_t.var_date}:{ordinal}'


def _createYnabTransactions(ynab_api_client: ynab.ApiClient, budget_id: str, transactions: list[NewTransaction], dry_run: bool):
    data = ynab.PostTransactionsWrapper()
    data.transactions = transactions

    transactions_api = ynab.TransactionsApi(ynab_api_client)
    if dry_run:
        logging.debug(
            'The request to TransactionsApi->create_transaction (dry_run in place): %s', data)
    else:
        api_response = transactions_api.create_transaction(budget_id, data)
        logging.debug(
            'The response of TransactionsApi->create_transaction: %s', api_response)
        logging.info('Saved transactions: %d, duplicate transactions: %d', len(
            api_response.data.transaction_ids), len(api_response.data.duplicate_import_ids))


def _isCreditIncomingTransfer(payee: str):
    return payee == 'TRANSFER FROM ACCOUNT'


def importCreditCsv(file: str, budget_id: str, account_id: str, ynab_api_client: ynab.ApiClient, dry_run: bool):
    csvfile = open(file, newline='')
    # UBS credit card CSV file has the first line with "sep=;"
    csvfile.readline()
    c = csv.DictReader(csvfile, delimiter=';')

    transactions = []
    for row in c:
        # Last 3 rows contain a summary -- stop before getting to it
        if not row['Account number']:
            break

        t = NewTransaction()
        t.account_id = account_id
        t.var_date = datetime.strptime(row['Purchase date'], '%d.%m.%Y').date()
        t.payee_name = row['Booking text']
        if row['Credit']:
            t.amount = int(float(row['Credit']) * 1000)
            t.cleared = TransactionClearedStatus.CLEARED
        elif row['Debit']:
            t.amount = -int(float(row['Debit']) * 1000)
            t.cleared = TransactionClearedStatus.CLEARED
        else:
            # Guess the transaction direction: it's usually debit unless it's a transfer from a debit account
            t.amount = -int(float(row['Amount']) * 1000)
            if _isCreditIncomingTransfer(t.payee_name):
                t.amount = -t.amount
            t.cleared = TransactionClearedStatus.UNCLEARED

        transactions.append(t)

    _populateImportIds(transactions)

    _createYnabTransactions(ynab_api_client, budget_id, transactions, dry_run)


def importDebitCsv(file: str, budget_id: str, account_id: str, ynab_api_client: ynab.ApiClient, dry_run: bool):
    csvfile = open(file, newline='')
    # UBS debit card CSV file has 9 info lines before the data table
    for _ in range(9):
        csvfile.readline()
    c = csv.DictReader(csvfile, delimiter=';')

    transactions = []
    for row in c:
        t = NewTransaction()
        t.account_id = account_id
        t.var_date = datetime.fromisoformat(row['Trade date']).date()
        t.payee_name = row['Description1']
        # In UBS CSV credit amount is positive and debit amount is negative
        str_amount = row['Credit'] if row['Credit'] else row['Debit']
        t.amount = int(float(str_amount) * 1000)
        t.cleared = TransactionClearedStatus.CLEARED

        transactions.append(t)

    _populateImportIds(transactions)

    _createYnabTransactions(ynab_api_client, budget_id, transactions, dry_run)


def importRevolutCsv(file: str, budget_id: str, account_id: str, ynab_api_client: ynab.ApiClient, dry_run: bool):
    csvfile = open(file, newline='')
    c = csv.DictReader(csvfile, delimiter=',')

    transactions = []
    for row in c:
        # Ignoring everything but Current for now
        if row['Product'] != 'Current':
            continue

        description = row['Description']
        # Ignore the spare change account and weird 'Balance migration to another region or legal entity' transfers
        if (row['Type'] == 'Transfer'
            and (description.startswith('To pocket ')
                 or description in ['Balance migration to another region or legal entity'])):
            continue

        t = NewTransaction()
        t.account_id = account_id
        t.var_date = datetime.fromisoformat(row['Started Date']).date()
        t.payee_name = row['Description']
        amount = int(float(row['Amount']) * 1000)
        fee = int(float(row['Fee']) * 1000)
        # TODO: Fee should probably not be deducted -- as least this is how I write it down in YNAB
        t.amount = amount - fee
        t.cleared = TransactionClearedStatus.CLEARED if row[
            'State'] == 'COMPLETED' else TransactionClearedStatus.UNCLEARED

        transactions.append(t)

    # Reverse transactions: Revolut CSV is old-to-new but _populateImportIds need new-to-old
    transactions.reverse()

    _populateImportIds(transactions)

    _createYnabTransactions(ynab_api_client, budget_id, transactions, dry_run)


Notification = namedtuple('Notification', ['date', 'message'])


def importUbsFromEmail(
    imap_server: str,
    email_address: str,
    password: str,
    folder: str,
    budget_id: str,
    account_map: dict[str, str],
    ynab_api_client: ynab.ApiClient,
    dry_run: bool
):
    """
    Imports UBS bank transaction notifications from email and creates corresponding transactions in YNAB.

    Connects to the specified IMAP server and mailbox, fetches UBS notification emails, parses transaction details,
    and creates YNAB transactions using the provided API client. Handles credit card outflows, inflows, and debit card
    notifications. Transactions are mapped to YNAB accounts using the `account_map` dictionary.
    Only UBS notification emails matching the expected format are processed.

    Args:
        imap_server: IMAP server to connect to for the mail. E.g. imap.gmail.com.
        email_address: login to the mail server.
        password: password for the mail server.
        folder: folder to open in your mailbox to limit the scope of emails processed.
            Use mailbox filtering rules to keep all UBS emails there (e.g., 'UBS').
        budget_id: YNAB budget ID to where transactions will be imported.
        account_map: mapping from UBS account/card identifiers (as found in notifications) to YNAB account IDs.
        ynab_api_client: An authenticated YNAB API client instance.
        dry_run: if True, transactions are parsed and logged but not sent to YNAB.

    Returns:
        None
    """
    notifications: list[Notification] = []
    with MailBox(imap_server).login(email_address, password, folder) as mailbox:
        d = datetime.today() - timedelta(days=DAYS_TO_FETCH_EMAILS)
        msgs = mailbox.fetch(criteria=AND(date_gte=d.date()), bulk=True)
        for m in msgs:
            x = re.search(UBS_NOTIFICATION_REGEXP, m.html, re.DOTALL)
            if not x:
                logging.warning(f'No UBS notification found in {m}')
                continue

            n = x.group(1).strip()
            notifications.append(Notification(m.date, n))

    logging.info('Read %d emails.', len(notifications))

    if not notifications:
        return

    transactions: list[NewTransaction] = []
    for i, n in enumerate(notifications):
        if p := re.search(UBS_CREDIT_CARD_OUTFLOW_REGEXP, n.message):
            # Notifications are for charged amounts only -- so the sum is negative
            sum = -float(p.group(1).replace('’', ''))
            card = p.group(2)
            payee = p.group(3)

            t = NewTransaction()
            t.account_id = account_map[card]
            if not t.account_id:
                raise KeyError(f'Card "{card}" not specified in account_map')
            t.var_date = n.date.date()
            t.payee_name = payee
            t.amount = int(sum * 1000)

            transactions.append(t)

            logging.debug(
                'Found credit card outflow notification: %s, %f to %s from %s', n.date, sum, payee, card)
        elif p := re.search(UBS_CREDIT_CARD_INFLOW_REGEXP, n.message):
            card = p.group(1)

            # Inflow email notifications from UBS don't contain amounts -- so we had to guess by the
            # presence of the debit outflow notification around
            debit_sum = 0
            if i > 0:
                nn = notifications[i - 1]
                p1 = re.search(UBS_DEBIT_CARD_REGEXP, nn.message)
                if p1 and abs(nn.date - n.date) < MAX_CREDIT_CARD_TRANSFT_TIMEDELTA and p1.group(2) == 'debited':
                    debit_sum = float(p1.group(3).replace('’', ''))

            if debit_sum == 0 and i < len(notifications) - 1:
                nn = notifications[i + 1]
                p1 = re.search(UBS_DEBIT_CARD_REGEXP, nn.message)
                if p1 and abs(nn.date - n.date) < MAX_CREDIT_CARD_TRANSFT_TIMEDELTA and p1.group(2) == 'debited':
                    debit_sum = float(p1.group(3).replace('’', ''))

            if debit_sum > 0:
                t = NewTransaction()
                t.account_id = account_map[card]
                if not t.account_id:
                    raise KeyError(f'Card "{card}" not specified in account_map')
                t.var_date = n.date.date()
                t.amount = int(debit_sum * 1000)

                transactions.append(t)

                logging.debug(
                    'Matched credit account inflow notification: %s, %f to %s', n.date, debit_sum, card)
            else:
                logging.warning(
                    'Credit inflow notification at %s doesn''t have a debit outflow nearby', n.date)
        elif p := re.search(UBS_DEBIT_CARD_REGEXP, n.message):
            account = p.group(1)
            action = p.group(2)
            sum = float(p.group(3).replace('’', ''))
            if action == 'debited':
                sum = -sum

            t = NewTransaction()
            t.account_id = account_map[account]
            if not t.account_id:
                raise KeyError(f'Account "{account}" not specified in account_map')
            t.var_date = n.date.date()
            t.amount = int(sum * 1000)

            transactions.append(t)

            logging.debug(
                'Found debit account notification: %s, %f from %s', n.date, sum, account)
        else:
            logging.warning('Unknown notification at %s: %s',
                            n.date, n.message)

    # Reverse transactions: IMAP returns is old-to-new but _populateImportIds need new-to-old
    transactions.reverse()

    _populateImportIds(transactions)

    _createYnabTransactions(ynab_api_client, budget_id, transactions, dry_run)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--access_token', help='Personal access token for accessing your YNAB account', required=True)
    parser.add_argument(
        '--budget_id', help='ID of the budget to perform operations with', required=True)
    parser.add_argument('--mode', help='What should be done',
                        choices=[MODE_IMPORT_CREDIT_CSV, MODE_IMPORT_DEBIT_CSV, MODE_IMPORT_REVOLUT_CSV, MODE_IMPORT_UBS_FROM_GMAIL], required=True)
    parser.add_argument(
        '--dry_run', help='Do not perform real REST API calls', action="store_true")
    parser.add_argument('--verbose', help='Verbose output',
                        action="store_true")
    # CSV-only arguments
    parser.add_argument('--account_id', help='ID of the destination account for CSV imports')
    parser.add_argument('--csv', help='CSV file to use for CSV import')
    # Email-only arguments
    parser.add_argument('--imap_server')
    parser.add_argument('--email_address')
    parser.add_argument('--email_password')
    parser.add_argument('--folder')
    parser.add_argument(
        '--account_map', help='A semicolon-separated key=value string mapping UBS card/account to YNAB account ID')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='[%(asctime)s] %(levelname)s: %(message)s')

    configuration = ynab.Configuration(
        access_token=args.access_token
    )

    with ynab.ApiClient(configuration) as ynab_api_client:
        if args.mode == MODE_IMPORT_UBS_FROM_GMAIL:
            if args.imap_server is None:
                parser.error('--imap_server is required for email import!')
            if args.email_address is None:
                parser.error('--email_address is required for email import!')
            if args.email_password is None:
                parser.error('--email_password is required for email import!')
            if args.folder is None:
                parser.error('--folder is required for email import!')
            if args.account_map is None:
                parser.error('--account_map is required for email import!')

            account_map_items = args.account_map.split(';')
            acc_map = dict(item.split('=') for item in account_map_items)

            importUbsFromEmail(args.imap_server, args.email_address, args.email_password, args.folder, args.budget_id,
                               acc_map, ynab_api_client, args.dry_run)
        else:
            if args.account_id is None:
                parser.error('--account_id is required for CSV import modes!')
            if args.csv is None:
                parser.error('--cvs is required for CSV import modes!')
            if args.mode == MODE_IMPORT_CREDIT_CSV:
                importCreditCsv(args.csv, args.budget_id,
                                args.account_id, ynab_api_client, args.dry_run)
            elif args.mode == MODE_IMPORT_DEBIT_CSV:
                importDebitCsv(args.csv, args.budget_id,
                               args.account_id, ynab_api_client, args.dry_run)
            elif args.mode == MODE_IMPORT_REVOLUT_CSV:
                importRevolutCsv(args.csv, args.budget_id,
                                 args.account_id, ynab_api_client, args.dry_run)
            else:
                raise ValueError(f'Mode "{args.mode}" is not supported')
