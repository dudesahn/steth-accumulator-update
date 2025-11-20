import brownie
from brownie import chain, Contract, ZERO_ADDRESS, accounts
import pytest
from utils import harvest_strategy, check_status, trade_handler_action


# test our harvest triggers
def test_triggers(
    gov,
    token,
    vault,
    strategist,
    whale,
    strategy,
    chain,
    amount,
    sleep_time,
    is_slippery,
    no_profit,
    profit_whale,
    profit_amount,
    target,
    base_fee_oracle,
    use_yswaps,
    is_gmx,
    use_v3,
    destination_vault,
    leave_on_invest,
    dont_report_loss,
    invest_all_first,
):
    # inactive strategy (0 DR and 0 assets) shouldn't be touched by keepers
    currentDebtRatio = vault.strategies(strategy)["debtRatio"]
    vault.updateStrategyDebtRatio(strategy, 0, {"from": gov})
    (profit, loss, extra) = harvest_strategy(
        use_v3,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        target,
        destination_vault,
    )

    # make sure that max delay would trigger it otherwise
    before = strategy.maxReportDelay()
    strategy.setMaxReportDelay(0)
    tx = strategy.harvestTrigger(0, {"from": gov})
    assert tx == True

    # need to harvest again to get all of the funds out w/ stETH accumulator's lagging peg profit
    # also turn off health check for this since we have no debt but profit
    strategy.setDoHealthCheck(False, {"from": gov})
    (profit, loss, extra) = harvest_strategy(
        use_v3,
        strategy,
        token,
        gov,
        profit_whale,
        0,
        target,
        destination_vault,
    )
    # check this based on what we're doing with our weth
    if leave_on_invest:
        assert profit == 0
        if not dont_report_loss:
            assert loss > 0
    else:
        assert profit > 0

    # strategy should be empty, except when we are reinvesting we seem to leave 1 wei sometimes
    if leave_on_invest:
        steth = Contract(strategy.stETH())
        before_steth = steth.sharesOf(strategy)
        if before_steth > 0:
            steth.transferShares(gov, before_steth, {"from": strategy})
    assert strategy.estimatedTotalAssets() == 0
    tx = strategy.harvestTrigger(0, {"from": gov})
    assert strategy.isActive() == False
    print("\nShould we harvest? Should be false.", tx)
    assert tx == False
    vault.updateStrategyDebtRatio(strategy, currentDebtRatio, {"from": gov})
    strategy.setMaxReportDelay(before)

    ## deposit to the vault after approving, no harvest yet
    starting_whale = token.balanceOf(whale)
    token.approve(vault, 2**256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
    newWhale = token.balanceOf(whale)
    starting_assets = vault.totalAssets()

    # update our min credit so harvest triggers true
    strategy.setCreditThreshold(1, {"from": gov})
    tx = strategy.harvestTrigger(0, {"from": gov})
    print("\nShould we harvest? Should be true.", tx)
    assert tx == True
    strategy.setCreditThreshold(1e24, {"from": gov})

    # test our manual harvest trigger
    strategy.setForceHarvestTriggerOnce(True, {"from": gov})
    tx = strategy.harvestTrigger(0, {"from": gov})
    print("\nShould we harvest? Should be true.", tx)
    assert tx == True

    # harvest the credit
    if leave_on_invest:
        # we may take a 1 wei loss here from above
        strategy.setDoHealthCheck(False, {"from": gov})
    (profit, loss, extra) = harvest_strategy(
        use_v3,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        target,
        destination_vault,
    )

    # should trigger false, nothing is ready yet, just harvested
    tx = strategy.harvestTrigger(0, {"from": gov})
    print("\nShould we harvest? Should be false.", tx)
    assert tx == False

    # simulate earnings
    chain.sleep(sleep_time)

    ################# GENERATE CLAIMABLE PROFIT HERE AS NEEDED #################
    # take profit in our destination vault
    trade_handler_action(
        strategy,
        profit_amount,
    )

    # set our max delay so we trigger true, then set it back to 21 days
    strategy.setMaxReportDelay(sleep_time - 1)
    tx = strategy.harvestTrigger(0, {"from": gov})
    print("\nShould we harvest? Should be True.", tx)
    assert tx == True
    strategy.setMaxReportDelay(86400 * 21)

    # harvest, wait
    (profit, loss, extra) = harvest_strategy(
        use_v3,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        target,
        destination_vault,
    )
    print("Profit:", profit, "Loss:", loss)
    chain.sleep(sleep_time)

    # harvest should trigger false because of oracle
    base_fee_oracle.setManualBaseFeeBool(False, {"from": base_fee_oracle.governance()})
    tx = strategy.harvestTrigger(0, {"from": gov})
    print("\nShould we harvest? Should be false.", tx)
    assert tx == False
    base_fee_oracle.setManualBaseFeeBool(True, {"from": base_fee_oracle.governance()})

    # harvest again to get the last of our profit with ySwaps
    if use_yswaps or is_gmx:
        (profit, loss, extra) = harvest_strategy(
            use_yswaps,
            strategy,
            token,
            gov,
            profit_whale,
            profit_amount,
            target,
        )

        # check our current status
        print("\nAfter yswaps extra harvest")
        strategy_params = check_status(strategy, vault)

        # make sure we recorded our gain properly
        if not no_profit:
            assert profit > 0

    # simulate five days of waiting for share price to bump back up
    chain.sleep(86400 * 5)
    chain.mine(1)

    # if we invest all loose WETH, we'll be realizing losses on withdrawal no matter what we do
    if not invest_all_first:
        # withdraw and confirm we made money, or at least that we have about the same
        vault.withdraw({"from": whale})
        if no_profit:
            assert (
                pytest.approx(token.balanceOf(whale), rel=RELATIVE_APPROX)
                == starting_whale
            )
        else:
            assert token.balanceOf(whale) > starting_whale
