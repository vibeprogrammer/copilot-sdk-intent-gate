"""The assistant's four custom tools and how each one is described to intent-agent."""

from __future__ import annotations

import json

from copilot import define_tool
from pydantic import BaseModel, Field

from canbank_assistant.ledger import Ledger
from intent_gate import ToolIntent

# What each tool call means, in the vocabulary of the IndyKite Knowledge Graph (canbank schema).
TOOL_INTENTS: dict[str, ToolIntent] = {
    "get_customer_profile": ToolIntent(
        template="View the customer profile of Customer {customer_id}",
        resources={"customer_id": "Customer"},
        actions=frozenset({"VIEW_CUSTOMER_PROFILE"}),
    ),
    "get_account_balance": ToolIntent(
        template="View the balance of Account {account_id}",
        resources={"account_id": "Account"},
        actions=frozenset({"VIEW_ACCOUNT_BALANCE"}),
    ),
    "get_invoice": ToolIntent(
        template="View Invoice {invoice_id}",
        resources={"invoice_id": "Invoice"},
        actions=frozenset({"VIEW_INVOICE"}),
    ),
    "transfer_funds": ToolIntent(
        template="Transfer {amount} NOK from Account {from_account_id} to Account {to_account_id}",
        resources={"from_account_id": "Account"},
        actions=frozenset({"TRANSFER_FROM_ACCOUNT"}),
    ),
}


class CustomerArgs(BaseModel):
    customer_id: str = Field(description="Customer id, e.g. 'bob'")


class AccountArgs(BaseModel):
    account_id: str = Field(description="Account id, e.g. 'acc-bob-checking'")


class InvoiceArgs(BaseModel):
    invoice_id: str = Field(description="Invoice id, e.g. 'inv-bob-0388'")


class TransferArgs(BaseModel):
    from_account_id: str = Field(description="Account to take the money from")
    to_account_id: str = Field(description="Account to put the money in")
    amount: str = Field(description="Amount in NOK, e.g. '250.00'")


def build_tools(ledger: Ledger) -> list:
    """Tools bound to one ledger. They do no authorization of their own (see ledger.py)."""

    async def get_customer_profile(p: CustomerArgs) -> str:
        return json.dumps(ledger.customer_profile(p.customer_id))

    async def get_account_balance(p: AccountArgs) -> str:
        return json.dumps(ledger.account_balance(p.account_id))

    async def get_invoice(p: InvoiceArgs) -> str:
        return json.dumps(ledger.invoice(p.invoice_id))

    async def transfer_funds(p: TransferArgs) -> str:
        return json.dumps(ledger.transfer(p.from_account_id, p.to_account_id, p.amount))

    return [
        define_tool(
            "get_customer_profile",
            description="Get a customer's profile: name, email, account ids and invoice ids.",
            handler=get_customer_profile,
            params_type=CustomerArgs,
        ),
        define_tool(
            "get_account_balance",
            description="Get the current balance of a bank account.",
            handler=get_account_balance,
            params_type=AccountArgs,
        ),
        define_tool(
            "get_invoice",
            description="Get an invoice: amount, status, due date and memo.",
            handler=get_invoice,
            params_type=InvoiceArgs,
        ),
        define_tool(
            "transfer_funds",
            description="Move money between two accounts.",
            handler=transfer_funds,
            params_type=TransferArgs,
        ),
    ]
