"""Clients for the three client systems, built from Settings."""

from northgate.clients.dispatch import DispatchClient
from northgate.clients.finance import FinanceClient
from northgate.clients.payroll import PayrollClient
from northgate.config import Settings


def build_clients(settings: Settings) -> tuple[PayrollClient, DispatchClient, FinanceClient]:
    payroll = PayrollClient(settings.payroll_url, settings.payroll_api_key)
    dispatch = DispatchClient(settings.dispatch_url, settings.dispatch_client_id, settings.dispatch_client_secret)
    finance = FinanceClient(settings.finance_url, settings.finance_user, settings.finance_password)
    return payroll, dispatch, finance
