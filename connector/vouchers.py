"""Accounting draft validation; posting transport is not yet implemented."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

@dataclass(frozen=True)
class MoneyDraft:
    kind: str
    party: str
    cash_bank: str
    amount: Decimal
    company: str = 'Upkar Agency'

    def validate(self):
        if self.kind not in ('Receipt', 'Payment'):
            raise ValueError('Select Receipt or Payment')
        if self.company != 'Upkar Agency':
            raise ValueError('Unexpected company')
        if not self.party.strip() or not self.cash_bank.strip():
            raise ValueError('Both ledgers are required')
        if self.party.strip().casefold() == self.cash_bank.strip().casefold():
            raise ValueError('Select distinct ledgers')
        try:
            value = Decimal(str(self.amount))
            if not value.is_finite() or value <= 0 or value != value.quantize(Decimal('.01')):
                raise ValueError('Enter a positive amount with at most two decimal places')
        except InvalidOperation as error:
            raise ValueError('Invalid amount') from error
        return value

    def entries(self):
        value = self.validate()
        party_value = value if self.kind == 'Receipt' else -value
        return ((self.party, party_value), (self.cash_bank, -party_value))
