from brownie import chain, Contract
from utils import harvest_strategy
import pytest, brownie


# test the our strategy's ability to deposit, harvest, and withdraw, with different optimal deposit tokens if we have them
def test_simple_harvest(
    gov,
    token,
    vault,
    whale,
    strategy,
    amount,
    sleep_time,
    is_slippery,
    no_profit,
    profit_whale,
    profit_amount,
    target,
    use_yswaps,
    is_gmx,
    use_v3,
    destination_vault,
    invest_all_first,
):
    ## deposit to the vault after approving
    starting_whale = token.balanceOf(whale)
    token.approve(vault, 2**256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
    newWhale = token.balanceOf(whale)

    print("Deposited to vault from whale")

    # harvest, store asset amount
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
    old_assets = vault.totalAssets()
    assert old_assets > 0
    assert strategy.estimatedTotalAssets() > 0

    # simulate profits
    chain.sleep(sleep_time)

    # harvest, store new asset amount
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
    # record this here so it isn't affected if we donate via ySwaps
    strategy_assets = strategy.estimatedTotalAssets()
    print("Profit from normal harvest:", profit)
    print("Loss from normal harvest:", loss)
    print("Profit from normal harvest with decimals:", profit / 1e18)

    # harvest again so the strategy reports the profit
    if use_yswaps or is_gmx:
        print("Using ySwaps for harvests")
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

    # do some checks for bugs from our old router version
    # harvesting with no profit would fail in old version eventually (takes 1 wei profit)
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
    print("Profit from no profit harvest #1:", profit)
    print("Loss from harvest:", loss)

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
    print("Profit from no profit harvest #2:", profit)
    print("Loss from harvest:", loss)

    # evaluate our current total assets
    new_assets = vault.totalAssets()

    # confirm we made money, or at least that we have about the same
    if no_profit:
        assert pytest.approx(new_assets, rel=RELATIVE_APPROX) == old_assets
    else:
        new_assets > old_assets

    # simulate five days of waiting for share price to bump back up
    chain.sleep(86400 * 5)
    chain.mine(1)

    # Display estimated APR
    print(
        "\nEstimated APR: ",
        "{:.2%}".format(
            ((new_assets - old_assets) * (365 * 86400 / sleep_time)) / (strategy_assets)
        ),
    )

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


# test migrating and pulling all of the funds out via the curve LP pool
def test_basic_harvest_empty(
    gov,
    token,
    vault,
    whale,
    strategy,
    amount,
    sleep_time,
    is_slippery,
    no_profit,
    profit_whale,
    profit_amount,
    target,
    use_yswaps,
    is_gmx,
    use_v3,
    destination_vault,
    leave_on_invest,
    dont_report_loss,
    invest_all_first,
):
    ## deposit to the vault after approving
    starting_whale = token.balanceOf(whale)
    token.approve(vault, 2**256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
    newWhale = token.balanceOf(whale)

    # shouldn't have more want in the strategy until we harvest in our whale's deposit
    if invest_all_first:
        assert strategy.wantBalance() == 0
    else:
        print("Loose WETH:", strategy.wantBalance() / 1e18)

    print("Deposited to vault from whale")

    # harvest, store asset amount
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
    old_assets = vault.totalAssets()
    assert old_assets > 0
    assert strategy.estimatedTotalAssets() > 0

    # simulate profits
    chain.sleep(sleep_time)

    # set DebtRatio to 0%
    vault.updateStrategyDebtRatio(strategy, 0, {"from": gov})

    # adjust our maxSingleTrade to 0 to prevent swapping out, but shouldn't see losses
    if leave_on_invest:
        assert strategy.wantBalance() == 0
    else:
        print("Loose WETH:", strategy.wantBalance() / 1e18)
    strategy.updateMaxSingleTrade(0, {"from": gov})
    steth = Contract("0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84")
    before_strategy_assets = strategy.estimatedTotalAssets()
    before_steth = steth.balanceOf(strategy)

    # harvest to send our funds back to the strategy
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

    # shouldn't have any losses, and shouldn't have moved any stETH out of strategy, and made some in profits
    # but we will have sent loose WETH to our vault
    if not invest_all_first:
        # we only report profit if we have loose WETH to use for it and we just set max trade to 0
        assert profit > 0
        assert strategy.estimatedTotalAssets() < before_strategy_assets
        assert vault.totalAssets() > old_assets
    else:
        # total assets is only updated via a vault.report in a harvest. we need loose weth for that to happen
        if leave_on_invest:
            assert vault.totalAssets() == old_assets
            # this will increase because we add stETH but don't send any WETH to the vault
            assert strategy.estimatedTotalAssets() > before_strategy_assets
        else:
            assert vault.totalAssets() > old_assets
            # we will send back all loose WETH we have
            assert strategy.estimatedTotalAssets() < before_strategy_assets
    assert loss == 0
    assert steth.balanceOf(strategy) > before_steth

    # simulate profits
    chain.sleep(sleep_time)
    next_steth = steth.balanceOf(strategy)
    next_strategy_assets = strategy.estimatedTotalAssets()

    # harvest to send our funds back to the strategy (but nothing will move since we can't swap stETH)
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

    # we can't take any profit if we can't convert stETH => WETH, but we shouldn't have losses and should have unrealized profits
    if not no_profit:
        assert profit == 0
        assert loss == 0
        assert steth.balanceOf(strategy) > next_steth
        assert strategy.estimatedTotalAssets() > next_strategy_assets

    # simulate profits
    chain.sleep(sleep_time)

    # adjust our maxSingleTrade back up to allow all the funds to exit
    strategy.updateMaxSingleTrade(1_000_000e18, {"from": gov})

    # We are failing in `vault.report()` to actually have all of the WETH that we think we have in profit…some of it is staying trapped as stETH and thus we revert.
    # we need to set peg to zero before we do a final report that empties everything out, in case we're going from full strategy to nothing

    # set peg to zero so we properly account for all funds
    strategy.updatePeg(0, {"from": gov})

    # harvest to send our funds back to the strategy
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

    # make sure we made a profit with no losses
    if not no_profit:
        assert profit > 0
        assert loss == 0
        assert vault.totalAssets() > old_assets
        assert (
            steth.balanceOf(strategy) <= 1
        )  # sometimes we can't clear all stETH out, known stETH bug: https://github.com/lidofinance/core/issues/442
        assert token.balanceOf(strategy) == 0

    # ideally we fully empty the strategy out when setting DR to 0 (or leave 1 wei of stETH)
    assert strategy.estimatedTotalAssets() <= 1

    print("Profit from our final harvest:", profit / 1e18)

    # withdraw and confirm we made money, or at least that we have about the same (profit whale has to be different from normal whale)
    vault.withdraw({"from": whale})
    if no_profit:
        assert (
            pytest.approx(token.balanceOf(whale), rel=RELATIVE_APPROX) == starting_whale
        )
    else:
        assert token.balanceOf(whale) > starting_whale
