import pytest
import brownie
from brownie import Contract, chain, interface
from utils import harvest_strategy, check_status


# test that emergency exit works properly
def test_emergency_exit(
    gov,
    token,
    vault,
    whale,
    strategy,
    amount,
    is_slippery,
    no_profit,
    sleep_time,
    profit_whale,
    profit_amount,
    target,
    use_yswaps,
    RELATIVE_APPROX,
    is_gmx,
    use_v3,
    destination_vault,
):
    ## deposit to the vault after approving
    starting_whale = token.balanceOf(whale)
    token.approve(vault, 2**256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
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

    # check our current status
    print("\nAfter first harvest")
    strategy_params = check_status(strategy, vault)

    # evaluate our current total assets
    old_assets = vault.totalAssets()
    initial_strategy_assets = strategy.estimatedTotalAssets()
    initial_debt = strategy_params["totalDebt"]
    starting_share_price = vault.pricePerShare()

    # simulate earnings
    chain.sleep(sleep_time)
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
    print("Harvest profit:", profit, "\n")

    # check our current status
    print("\nBefore exit, after second harvest")
    strategy_params = check_status(strategy, vault)

    # yswaps will not have taken this first batch of profit yet
    if use_yswaps or is_gmx:
        assert strategy_params["totalGain"] == 0
    else:
        assert strategy_params["totalGain"] > 0

    # set emergency and exit, then confirm that the strategy has no funds
    strategy.setEmergencyExit({"from": gov})
    chain.sleep(sleep_time)

    # check our current status
    print("\nAfter exit + before third harvest")
    strategy_params = check_status(strategy, vault)

    # debtOutstanding should be the entire debt, DR and credit should be zero
    assert vault.debtOutstanding(strategy) == strategy_params["totalDebt"] > 0
    assert vault.creditAvailable(strategy) == 0
    assert strategy_params["debtRatio"] == 0

    ################# CLAIM ANY REMAINING REWARDS. ADJUST AS NEEDED PER STRATEGY. #################
    # again, harvests in emergency exit don't enter prepareReturn, so we need to claim our rewards manually
    # router the target vault still yields as normal without a harvest

    # harvest to send funds back to vault
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
    print("Harvest profit:", profit, "\n")

    # check our current status
    print("\nAfter third harvest")
    strategy_params = check_status(strategy, vault)

    # yswaps should have finally taken our first round of profit
    assert strategy_params["totalGain"] > 0

    # debtOutstanding, debt, credit should now be zero, but we will still send any earned profits immediately back to vault
    assert (
        vault.debtOutstanding(strategy)
        == strategy_params["totalDebt"]
        == vault.creditAvailable(strategy)
        == 0
    )

    # yswaps needs another harvest to get the final bit of profit to the vault
    if use_yswaps or is_gmx:
        old_gain = strategy_params["totalGain"]
        (profit, loss, extra) = harvest_strategy(
            use_yswaps,
            strategy,
            token,
            gov,
            profit_whale,
            profit_amount,
            target,
        )
        print("Harvest profit:", profit, "\n")

        # check our current status
        print("\nAfter yswaps extra harvest")
        strategy_params = check_status(strategy, vault)

        # make sure we recorded our gain properly
        if not no_profit:
            assert strategy_params["totalGain"] > old_gain

    # strategy should be completely empty now, even if no profit or slippery
    assert strategy.estimatedTotalAssets() == 0

    # simulate 5 days of waiting for share price to bump back up
    chain.sleep(86400 * 5)
    chain.mine(1)

    # check our current status
    print("\nAfter sleep for share price")
    strategy_params = check_status(strategy, vault)

    # share price should have gone up, without loss except for special cases
    if no_profit:
        assert (
            pytest.approx(vault.pricePerShare(), rel=RELATIVE_APPROX)
            == starting_share_price
        )
    else:
        assert vault.pricePerShare() > starting_share_price
        assert strategy_params["totalLoss"] == 0

    # withdraw and confirm we made money, or at least that we have about the same (profit whale has to be different from normal whale)
    vault.withdraw({"from": whale})
    if no_profit:
        assert (
            pytest.approx(token.balanceOf(whale), rel=RELATIVE_APPROX) == starting_whale
        )
    else:
        assert token.balanceOf(whale) > starting_whale


# test emergency exit, but with a donation (profit)
def test_emergency_exit_with_profit(
    gov,
    token,
    vault,
    whale,
    strategy,
    amount,
    is_slippery,
    no_profit,
    sleep_time,
    profit_whale,
    profit_amount,
    target,
    use_yswaps,
    RELATIVE_APPROX,
    is_gmx,
    use_v3,
    destination_vault,
    is_migration,
):
    ## deposit to the vault after approving
    starting_whale = token.balanceOf(whale)
    token.approve(vault, 2**256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
    (first_profit, loss, extra) = harvest_strategy(
        use_v3,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        target,
        destination_vault,
    )

    # check our current status
    print("\nAfter first harvest")
    strategy_params = check_status(strategy, vault)

    # evaluate our current total assets
    old_assets = vault.totalAssets()
    initial_strategy_assets = strategy.estimatedTotalAssets()
    initial_debt = strategy_params["totalDebt"]
    starting_share_price = vault.pricePerShare()
    loose_want = token.balanceOf(vault)
    # in the V2 dai vault we have some extra debt not assigned to our main strategy
    other_debt = vault.totalDebt() - strategy_params["totalDebt"]

    # simulate earnings
    chain.sleep(sleep_time)
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

    # check our current status
    print("\nAfter second harvest")
    strategy_params = check_status(strategy, vault)

    # yswaps will not have taken this first batch of profit yet
    if use_yswaps or is_gmx:
        assert strategy_params["totalGain"] == 0
    else:
        assert strategy_params["totalGain"] > 0

    # turn off health check since this will be an extra profit from the donation
    token.transfer(strategy, profit_amount, {"from": profit_whale})
    strategy.setDoHealthCheck(False, {"from": gov})

    # check our current status
    print("\nBefore exit, after donation")
    strategy_params = check_status(strategy, vault)

    # we should have more assets but the same debt
    assert strategy.estimatedTotalAssets() > initial_strategy_assets
    if is_migration:
        assert strategy_params["totalDebt"] == initial_debt + first_profit
    else:
        assert strategy_params["totalDebt"] == initial_debt

    # set emergency and exit
    strategy.setEmergencyExit({"from": gov})

    # check our current status
    print("\nAfter exit + before third harvest")
    strategy_params = check_status(strategy, vault)

    # debtOutstanding uses both totalAssets and totalDebt
    # with 10_000 DR they should all be the same (since we haven't taken donation as profit yet)
    if is_migration:
        assert (
            strategy_params["totalDebt"]
            == initial_debt + loose_want
            == old_assets - other_debt
            == vault.debtOutstanding(strategy)
        )
    else:
        assert (
            strategy_params["totalDebt"]
            == initial_debt
            == old_assets
            == vault.debtOutstanding(strategy)
        )
    chain.sleep(sleep_time)

    ################# CLAIM ANY REMAINING REWARDS. ADJUST AS NEEDED PER STRATEGY. #################
    # again, harvests in emergency exit don't enter prepareReturn, so we need to claim our rewards manually
    # router the target vault still yields as normal without a harvest

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

    # check our current status
    print("\nAfter third harvest")
    strategy_params = check_status(strategy, vault)

    # yswaps should have finally taken our first round of profit
    assert strategy_params["totalGain"] > 0

    # debtOutstanding, debt, credit should now be zero, but we will still send any earned profits immediately back to vault
    assert (
        vault.debtOutstanding(strategy)
        == strategy_params["totalDebt"]
        == vault.creditAvailable(strategy)
        == 0
    )

    # yswaps needs another harvest to get the final bit of profit to the vault
    if use_yswaps or is_gmx:
        old_gain = strategy_params["totalGain"]
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
            assert strategy_params["totalGain"] > old_gain

    # confirm that the strategy has no funds
    assert strategy.estimatedTotalAssets() == 0

    # simulate 5 days of waiting for share price to bump back up
    chain.sleep(86400 * 5)
    chain.mine(1)

    # check our current status
    print("\nAfter sleep for share price")
    strategy_params = check_status(strategy, vault)

    # share price should have gone up, without loss except for special cases
    if no_profit:
        assert (
            pytest.approx(vault.pricePerShare(), rel=RELATIVE_APPROX)
            == starting_share_price
        )
    else:
        assert vault.pricePerShare() > starting_share_price
        assert strategy_params["totalLoss"] == 0

    # withdraw and confirm we made money, or at least that we have about the same (profit whale has to be different from normal whale)
    vault.withdraw({"from": whale})
    if no_profit:
        assert (
            pytest.approx(token.balanceOf(whale), rel=RELATIVE_APPROX) == starting_whale
        )
    else:
        assert token.balanceOf(whale) > starting_whale


# test emergency exit, but after somehow losing all of our assets (oopsie)
def test_emergency_exit_with_loss(
    gov,
    token,
    vault,
    whale,
    strategy,
    amount,
    is_slippery,
    no_profit,
    sleep_time,
    profit_whale,
    profit_amount,
    target,
    use_yswaps,
    old_vault,
    RELATIVE_APPROX,
    is_gmx,
    use_v3,
    destination_vault,
    is_migration,
):
    ## deposit to the vault after approving
    starting_whale = token.balanceOf(whale)
    token.approve(vault, 2**256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
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

    # check our current status
    print("\nBefore funds loss, after first harvest")
    strategy_params = check_status(strategy, vault)

    # evaluate our current total assets
    old_assets = vault.totalAssets()
    initial_debt = strategy_params["totalDebt"]
    starting_share_price = vault.pricePerShare()
    initial_strategy_assets = strategy.estimatedTotalAssets()
    loose_want = token.balanceOf(vault)
    # in the V2 dai vault we have some extra debt not assigned to our main strategy
    other_debt = vault.totalDebt() - strategy_params["totalDebt"]

    ################# SEND ALL FUNDS AWAY. ADJUST AS NEEDED PER STRATEGY. #################
    # send away all funds, will need to alter this based on strategy
    to_send = destination_vault.balanceOf(strategy)
    destination_vault.transfer(gov, to_send, {"from": strategy})
    assert strategy.estimatedTotalAssets() == 0

    ################# SET FALSE IF PROFIT EXPECTED. ADJUST AS NEEDED. #################
    # set this true if no profit on this test. it is normal for a strategy to not generate profit here.
    # realistically only wrapped tokens or every-block earners will see profits (convex, etc).
    # also checked in test_change_debt
    no_profit = False

    # check our current status
    print("\nBefore dust transfer, after main fund transfer")
    strategy_params = check_status(strategy, vault)

    # we shouldn't have taken any actual losses yet, and debt/DR/share price should all still be the same
    assert strategy_params["debtRatio"] == 10_000
    assert strategy_params["totalLoss"] == 0
    if is_migration:
        assert (
            strategy_params["totalDebt"]
            == initial_debt
            == old_assets - loose_want - other_debt
        )
        assert vault.pricePerShare() >= starting_share_price
    else:
        assert strategy_params["totalDebt"] == initial_debt == old_assets
        assert vault.pricePerShare() == starting_share_price

    # if slippery, then assets may differ slightly from debt
    if is_slippery:
        assert (
            pytest.approx(initial_debt, rel=RELATIVE_APPROX) == initial_strategy_assets
        )
    else:
        assert initial_debt == initial_strategy_assets

    # confirm we emptied the strategy
    assert strategy.estimatedTotalAssets() == 0

    # our whale donates 5 wei to the vault so we don't divide by zero (needed for older vaults)
    if old_vault and not is_migration:
        dust_donation = 5
        token.transfer(strategy, dust_donation, {"from": whale})
        assert strategy.estimatedTotalAssets() == dust_donation

    # check our current status
    print("\nBefore exit, after funds transfer out + dust transfer in")
    strategy_params = check_status(strategy, vault)

    # we shouldn't have taken any actual losses yet, and debt/DR/share price should all still be the same
    assert strategy_params["debtRatio"] == 10_000
    assert strategy_params["totalLoss"] == 0
    if is_migration:
        assert (
            strategy_params["totalDebt"]
            == initial_debt
            == old_assets - loose_want - other_debt
        )
        assert vault.pricePerShare() >= starting_share_price
    else:
        assert strategy_params["totalDebt"] == initial_debt == old_assets
        assert vault.pricePerShare() == starting_share_price
    assert vault.debtOutstanding(strategy) == 0

    # set emergency and exit, but turn off health check since we're taking a huge L
    strategy.setEmergencyExit({"from": gov})

    # check our current status
    print("\nAfter exit + before second harvest")
    strategy_params = check_status(strategy, vault)

    # we shouldn't have taken any actual losses yet, only DR and debtOutstanding should have changed
    if is_migration:
        assert vault.pricePerShare() >= starting_share_price
    else:
        assert vault.pricePerShare() == starting_share_price
    assert strategy_params["debtRatio"] == 0
    assert strategy_params["totalLoss"] == 0
    assert vault.creditAvailable(strategy) == 0
    assert strategy_params["debtRatio"] == 0

    # debtOutstanding uses both totalAssets and totalDebt, with 10_000 DR they should all be the same
    if is_migration:
        assert (
            strategy_params["totalDebt"]
            == initial_debt
            == old_assets - loose_want - other_debt
            == vault.debtOutstanding(strategy)
        )
    else:
        assert (
            strategy_params["totalDebt"]
            == initial_debt
            == old_assets
            == vault.debtOutstanding(strategy)
        )

    # if slippery, then assets may differ slightly from debt
    if is_slippery:
        assert (
            pytest.approx(initial_debt, rel=RELATIVE_APPROX) == initial_strategy_assets
        )
    else:
        assert initial_debt == initial_strategy_assets

    ################# CLAIM ANY REMAINING REWARDS. ADJUST AS NEEDED PER STRATEGY. #################
    # again, harvests in emergency exit don't enter prepareReturn, so we need to claim our rewards manually
    # router the target vault still yields as normal without a harvest

    # take our losses
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

    # check our current status
    print("\nAfter second harvest (losses taken)")
    strategy_params = check_status(strategy, vault)

    # DR goes to zero, loss is > 0, gain and debt should be zero, share price zero (bye-bye assets 💀)
    assert strategy_params["debtRatio"] == 0
    assert strategy_params["totalLoss"] > 0
    if is_migration:
        assert strategy_params["totalDebt"] == 0
        assert vault.pricePerShare() >= 0
    else:
        assert strategy_params["totalDebt"] == strategy_params["totalGain"] == 0
        assert vault.pricePerShare() == 0

    # yswaps needs another harvest to get the final bit of profit to the vault
    if use_yswaps or is_gmx:
        old_gain = strategy_params["totalGain"]
        (profit, loss, extra) = harvest_strategy(
            use_yswaps,
            strategy,
            token,
            gov,
            profit_whale,
            profit_amount,
            target,
        )
        print("Profit:", profit)

        # check our current status
        print("\nAfter yswaps extra harvest")
        strategy_params = check_status(strategy, vault)

        # make sure we recorded our gain properly
        if not no_profit:
            assert strategy_params["totalGain"] > old_gain

    # confirm that the strategy has no funds, even for old vaults with the dust donation
    assert strategy.estimatedTotalAssets() == 0

    # vault should also have no assets or just profit, except old ones will also have 5 wei
    # gmx will also have taken some profit above, but important to note that only realized profits count toward vault assets
    expected_assets = 0
    if not is_migration:  # migration messes this all up
        if use_yswaps and not no_profit:
            expected_assets += profit_amount
        if old_vault:
            expected_assets += dust_donation
        if is_gmx:
            expected_assets += profit
        assert vault.totalAssets() == expected_assets

    # simulate 5 days of waiting for share price to bump back up
    chain.sleep(86400 * 5)
    chain.mine(1)

    # check our current status
    print("\nAfter sleep for share price")
    strategy_params = check_status(strategy, vault)

    # withdraw and see how down bad we are, confirming we can withdraw from an empty (or mostly empty) vault
    vault.withdraw({"from": whale})
    print(
        "Raw loss:",
        (starting_whale - token.balanceOf(whale)) / 1e18,
        "Percentage:",
        (starting_whale - token.balanceOf(whale)) / starting_whale,
    )
    print("Share price:", vault.pricePerShare() / 1e18)
