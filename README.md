# UBS to YNAB

This is a Python script capable of importing transactions from [UBS](http://ubs.com) (CSVs and email notifications) and [Revolut](http://revolut.com) (CSVs; despite the script name 🤷🏼‍♂️) into your [YNAB](http://ynab.com) budget using YNAB REST API: https://api.ynab.com/v1.  

Transactions are imported with the `import_id` field populated to `UBS2YNAB:$AMOUNT:$DATE:$ORDINAL` where `$AMOUNT` is the transaction amount in milliunits, `$DATE` is the transaction date in ISO format and `$ORDINAL` is the 0-based ordinal within all transactions at the same date with the same amount. This allows safely re-running the script with the same inputs as transactions are deduplicated based on the `import_id`.

## Operations modes

Each mode requires a specific value of the `--mode` flag to be passed to the script. But the following flags are always required:
- `--access_token`: YNAB API access token. See https://api.ynab.com/#access-token-usage.
- `--budget_id`: YNAB budget ID to operate upon.

On top of that there are 2 optional flags:
- `--verbose`: enables debug logging.
- `--dry_run`: performs all the tasks but doesn't do the final YNAB API call; logs the request instead (`--verbose` should be used to see it).

### UBS CSV import

For the unknown reason UBS uses 2 different CSV formats: one used for debit accounts (savings accounts are also here), another -- for credit cards. Thus there are 2 different `--mode` flag values: `import_debit_csv`, `import_credit_csv`. No matter the mode, the `--csv` flag should be provided to point the the CSV itself. 

`cleared` field specifics:
- Credit CSVs differentiate between uncleared (only the `Amount` column) and cleared (also `Debit`/`Credit` column) transactions -- the scripts follow this logic.
- Debit CSVs don't -- so the script always creates such transactions as cleared.

Usage example:
```
$ python ubs2ynab.py \
  --access_token=my-access-token \
  --budget_id=bbbbbbbb-1234-1234-1234-123456789012 \
  --account_id=aaaaaaaa-1234-1234-1234-123456789012 \
  --mode=import_debit_csv \
  --csv=transactions.csv
```

### UBS email notifications import

For every account and credit card UBS can be configured to send you email notifications on corresponding transactions. The script can log into your mailbox, fetch these notifications and create corresponding transactions in YNAB. The idea is to run it regularly (e.g. with `crontab`).  

For this mode the following additional flags are required:
- `--imap_server`: the IMAP server to connect to for the mail. E.g. `imap.gmail.com`.
- `--email_address`: the login to the mail server.
- `--email_password`: the password for the mail server. For GMail special app passwords could be created at https://myaccount.google.com/apppasswords.
- `--folder`: the folder to open in your mailbox. This is the only way (execpt for dates: no older that 1 day ago) to limit the scope of what the script fetched. For GMail multi-level labels like `Finance/UBS` can be used.
- `--account_map`: a semicolon-separated list of UBS account/card aliases (see "UBS configuration" below) mapped to corresponding YNAB account IDs. E.g. `Checking=aaaaaaaa-1234-1234-1234-123456789012;Savings=oooooooo-1234-1234-1234-123456789012`.

All the imported this way transactions are not cleared. You are supposed to mark them as so during reconciliation.  

Usage example:
```
python3 ubs2ynab.py \
  --access_token=9my-access-token \
  --budget_id=bbbbbbbb-1234-1234-1234-123456789012 \
  --mode=import_ubs_email_notifications \
  --imap_server=imap.gmail.com \
  --email_address=user@gmail.com \
  --email_password="aaaa bbbb cccc dddd" \
  --folder=Finance/UBS \
  --account_map="Checking=aaaaaaaa-1234-1234-1234-123456789012;Savings=oooooooo-1234-1234-1234-123456789012"
```

#### UBS configuration

1. Open E-Banking.
1. Go to Settings > Notifications and Mobile Banking App.
1. Click the "Notifications" menu item.
1. For every account and card you have in YNAB add a "transaction" rule to notify on `Credit >= 0.00` and `Debit <= 0.00` (for cards `0.00` is still not allowed and the minimal limit is `0.10`; but this is almost as 0 Switzerland). Rules should send you an email -- make sure the address is specified.  
Note the aliases specified in the rules: this is how corresponding accounts/cards will be represented in email notifications.
1. Double check that all rules are enabled: note the right-most button is ⏸, not ▶.

#### Example crontab config

Start a cron editor (`crontab -e`) and create the following task there:
```
45 * * * * /home/user/dev/ubs2ynab/.venv/bin/python3 /home/user/dev/ubs2ynab/ubs2ynab.py --access_token=9my-access-token --budget_id=bbbbbbbb-1234-1234-1234-123456789012 --mode=import_ubs_email_notifications --imap_server=imap.gmail.com --email_address=user@gmail.com --email_password="aaaa bbbb cccc dddd" --folder=Finance/UBS --account_map="Checking=aaaaaaaa-1234-1234-1234-123456789012;Savings=oooooooo-1234-1234-1234-123456789012" >> /home/user/dev/ubs2ynab/cron.log 2>&1
```

#### Specifics

UBS email notifications are built for people to read, not for machines. As a result they are not as precise as they could be and the script has to deal with several inconveniencies: 

* Debit account notification emails don't have a merchant name. So it stays empty in YNAB.
* Credit card inflow notification emails don't have an amount. So script checks for the notifications within 1 minute around this one -- and in case it's a debit account outflow, the script takes the amount from it.  

### Revolut CSV import  

[Revolut](http://revolut.com) provides a possibility to download your account transactions as CSV (although it's called "Excel" on their site). This CSV can be fed to the script exactly as UBS CSVs could -- accurate to the `--mode` flag which should be `import_revolut_csv` now.  

Revolut CSVs distinguish cleared and uncleared transactions (with the `State` column), so the script respects that.  

In case you have spare change pockets in Revolut, they are represented as separate `TRANSFER` transactions in addition to every normal transaction. These are ignored by the script as it's so far expected to not have such spare change pockets in YNAB.

## Development

```
source .venv/bin/activate
python -m pip install ynab
python -m pip install imap-tools
echo "Ready to develop!"
```
