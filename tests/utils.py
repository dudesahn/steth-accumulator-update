import pytest
import brownie
from brownie import interface, chain, accounts, Contract
import time


# returns (profit, loss) of a harvest
def harvest_strategy(
    use_v3,
    strategy,
    token,
    gov,
    profit_whale,
    profit_amount,
    destination_strategy,
    destination_vault,
):

    # reset everything with a sleep and mine
    chain.sleep(1)
    chain.mine(1)

    # add in any custom logic needed here, for instance with router strategy (also reason we have a destination strategy).
    # also add in any custom logic needed to get raw reward assets to the strategy (like for liquity)

    ####### ADD LOGIC AS NEEDED FOR CLAIMING/SENDING REWARDS TO STRATEGY #######
    # usually this is automatic, but it may need to be externally triggered

    # since we don't use yswaps for the main strategy, we don't need to ever prevent profit in the destination vault
    # send profit to our destination vault's strategy
    # if we don't want to harvest our destination strategy, we pass profit_amount to zero
    extra = 0

    # check loose want before harvest
    print("Loose want before harvest:", strategy.wantBalance() / 1e18)
    print("Vault balance of want:", token.balanceOf(strategy.vault()) / 1e18)

    # create profit in steth
    trade_handler_action(strategy, profit_amount)

    # we can use the tx for debugging if needed
    tx = strategy.harvest({"from": gov})
    profit = tx.events["Harvested"]["profit"]
    loss = tx.events["Harvested"]["loss"]
    print("Debt Payment:", tx.events["Harvested"]["debtPayment"])
    print("Debt Outstanding:", tx.events["Harvested"]["debtOutstanding"])
    if loss > 0:
        print("🚨 Harvest loss:", loss / 1e18)
    if profit > 0:
        print("💰 Harvest profit:", profit / 1e18)

    # assert there are no loose funds in strategy after a harvest
    print("Loose want after harvest:", strategy.wantBalance() / 1e18)
    print("Vault balance of want:", token.balanceOf(strategy.vault()) / 1e18)

    # I think we should only ever have 1 wei extra here
    # assert strategy.wantBalance() <= 1

    # reset everything with a sleep and mine
    chain.sleep(1)
    chain.mine(1)

    # return our profit, loss
    return (profit, loss, extra)


# simulate the trade handler sweeping out assets and sending back profit
def trade_handler_action(strategy, profit_amount):
    ####### ADD LOGIC AS NEEDED FOR SENDING REWARDS OUT AND PROFITS IN #######
    # in this strategy, we actually need to send profits to our destination strategy and harvest that

    # ******* need to airdrop in some steth to simulate the rebase
    steth_whale = accounts.at("0x176F3DAb24a159341c0509bB36B833E7fdd0a132", force=True)
    steth = Contract("0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84")
    # only airdrop in profit if our strategy has TVL that would be generating yield
    if strategy.estimatedTotalAssets() > 1 and profit_amount > 0:
        steth.transfer(strategy, profit_amount, {"from": steth_whale})

    # sleep 5 days so share price normalizes
    chain.sleep(86400 * 5)
    chain.mine(1)

    # we don't use extra for anything here
    return 0


# do a check on our strategy and vault of choice
def check_status(
    strategy,
    vault,
):
    # check our current status
    strategy_params = vault.strategies(strategy)
    vault_assets = vault.totalAssets()
    debt_outstanding = vault.debtOutstanding(strategy)
    credit_available = vault.creditAvailable(strategy)
    total_debt = vault.totalDebt()
    share_price = vault.pricePerShare()
    strategy_debt = strategy_params["totalDebt"]
    strategy_loss = strategy_params["totalLoss"]
    strategy_gain = strategy_params["totalGain"]
    strategy_debt_ratio = strategy_params["debtRatio"]
    strategy_assets = strategy.estimatedTotalAssets()

    # print our stuff
    print("Vault Assets:", vault_assets)
    print("Strategy Debt Outstanding:", debt_outstanding)
    print("Strategy Credit Available:", credit_available)
    print("Vault Total Debt:", total_debt)
    print("Vault Share Price:", share_price)
    print("Strategy Total Debt:", strategy_debt)
    print("Strategy Total Loss:", strategy_loss)
    print("Strategy Total Gain:", strategy_gain)
    print("Strategy Debt Ratio:", strategy_debt_ratio)
    print("Strategy Estimated Total Assets:", strategy_assets, "\n")

    # print simplified versions if we have something more than dust
    token = interface.IERC20(vault.token())
    if vault_assets > 10:
        print(
            "Decimal-Corrected Vault Assets:", vault_assets / (10 ** token.decimals())
        )
    if debt_outstanding > 10:
        print(
            "Decimal-Corrected Strategy Debt Outstanding:",
            debt_outstanding / (10 ** token.decimals()),
        )
    if credit_available > 10:
        print(
            "Decimal-Corrected Strategy Credit Available:",
            credit_available / (10 ** token.decimals()),
        )
    if total_debt > 10:
        print(
            "Decimal-Corrected Vault Total Debt:", total_debt / (10 ** token.decimals())
        )
    if share_price > 10:
        print("Decimal-Corrected Share Price:", share_price / (10 ** token.decimals()))
    if strategy_debt > 10:
        print(
            "Decimal-Corrected Strategy Total Debt:",
            strategy_debt / (10 ** token.decimals()),
        )
    if strategy_loss > 10:
        print(
            "Decimal-Corrected Strategy Total Loss:",
            strategy_loss / (10 ** token.decimals()),
        )
    if strategy_gain > 10:
        print(
            "Decimal-Corrected Strategy Total Gain:",
            strategy_gain / (10 ** token.decimals()),
        )
    if strategy_assets > 10:
        print(
            "Decimal-Corrected Strategy Total Assets:",
            strategy_assets / (10 ** token.decimals()),
        )

    return strategy_params
