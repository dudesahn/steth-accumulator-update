import brownie
from brownie import Contract, chain, ZERO_ADDRESS, interface, accounts
import pytest
from utils import harvest_strategy, check_status


# this test makes sure we can still harvest without any assets but still get our profits
# can also test here whether we claim rewards from an empty strategy, some protocols will revert
def test_empty_strat(
    gov,
    token,
    vault,
    whale,
    strategy,
    amount,
    profit_whale,
    profit_amount,
    target,
    use_yswaps,
    old_vault,
    is_slippery,
    RELATIVE_APPROX,
    vault_address,
    sleep_time,
    is_gmx,
    use_v3,
    destination_vault,
    is_migration,
):
    # realistically for tests like these, would probably be better to just use 0 profit on the first harvest,
    # that way we could achieve the desired impact of having a fully empty strategy instead of pretending it's some
    # caveat of the migration that we have profit on the first harvest...we're choosing to have that profit, or at least,
    # we're choosing to add additional profit to any that might be brought over from the migration

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
    loose_want = token.balanceOf(vault)
    # in the V2 WETH vault we have some extra debt not assigned to our main strategy (or the router). ~2e8 wei of WETH.
    other_debt = vault.totalDebt() - strategy_params["totalDebt"]

    # sleep to get some yield
    chain.sleep(sleep_time)

    ################# SEND ALL FUNDS AWAY. ADJUST AS NEEDED PER STRATEGY. #################
    before_weth = strategy.wantBalance()
    before_steth = strategy.stethBalance()
    steth = Contract(strategy.stETH())
    if before_weth > 0:
        token.transfer(gov, before_weth, {"from": strategy})
    steth.transfer(gov, before_steth, {"from": strategy})
    assert strategy.estimatedTotalAssets() == 0  # we may not get all of the stETH out

    # confirm we emptied the strategy
    assert strategy.estimatedTotalAssets() == 0

    # check that our losses are approximately the whole strategy
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
    # old vaults also don't have the totalIdle var
    if old_vault:
        if not is_migration:
            dust_donation = 5
            token.transfer(strategy, dust_donation, {"from": whale})
            assert strategy.estimatedTotalAssets() == dust_donation
    else:
        if (
            not is_migration
        ):  # seems that 0.4.3 don't actually have totalIdle either, do this as a workaround for this repo
            total_idle = vault.totalIdle()
            assert total_idle == 0

    # check our current status
    print("\nBefore harvest, after funds transfer out + dust transfer in")
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

    # accept our losses, sad day 🥲
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
    assert loss > 0

    # check our status
    print("\nAfter our big time loss")
    strategy_params = check_status(strategy, vault)

    # DR goes to zero, loss is > 0, gain and debt should be near zero (zero for new vaults), share price also nearr zero (bye-bye assets 💀)
    if old_vault and not is_migration:
        assert strategy_params["debtRatio"] == 1
    else:
        # note that since the DAI vault doesn't have all debt allocated to our strategy, we actually don't get this 100% reduction in debtRatio
        # in the V2 WETH vault we have some extra debt not assigned to our main strategy (or the router). ~2e8 wei of WETH.
        assert strategy_params["debtRatio"] == 1
    assert strategy_params["totalLoss"] > 0
    if not is_gmx:
        if is_migration:
            assert strategy_params["totalGain"] > 0
            assert vault.pricePerShare() > 0
        else:
            assert strategy_params["totalGain"] == 0
            assert vault.pricePerShare() == 0

    # vault should also have no assets, except old ones will have 5 wei
    if old_vault:
        if not is_migration:
            assert strategy_params["totalDebt"] == dust_donation == vault.totalAssets()
            assert strategy.estimatedTotalAssets() <= dust_donation
    else:
        if not use_v3:
            # same as above, not all debt is allocated here and also we don't have total Idle on the dai vault
            assert strategy_params["totalDebt"] == 0 == vault.totalAssets()
            total_idle = vault.totalIdle()
            assert total_idle == 0
        if use_yswaps:
            assert strategy.estimatedTotalAssets() == profit_amount
        elif is_gmx:
            assert strategy.estimatedTotalAssets() == extra
        else:
            if not use_v3:
                assert strategy.estimatedTotalAssets() == 0

    print("Total supply:", vault.totalSupply())

    # some profits fall from the heavens
    # this should be used to pay down debt vs taking profits
    token.transfer(strategy, profit_amount, {"from": profit_whale})
    print("\nAfter our donation")
    strategy_params = check_status(strategy, vault)
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
    assert profit > 0
    share_price = vault.pricePerShare()
    assert share_price > 0
    print("Share price:", share_price)


# this test makes sure we can still harvest without any profit and not revert
# for some strategies it may be impossible to harvest without generating profit, especially if not using yswaps
def test_no_profit(
    gov,
    token,
    vault,
    whale,
    strategy,
    amount,
    profit_whale,
    profit_amount,
    target,
    use_yswaps,
    sleep_time,
    is_gmx,
    use_v3,
    destination_vault,
    is_migration,
):
    ## deposit to the vault after approving
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

    # store our starting share price
    starting_share_price = vault.pricePerShare()

    # normally we would sleep here, but we are intentionally trying to avoid profit, so we don't

    # if are using yswaps and we don't want profit, don't use yswaps (False for first argument).
    # Or just don't harvest our destination strategy, can pass 0 for profit_amount and use if statement in utils
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

    # check our current status
    print("\nAfter harvest")
    strategy_params = check_status(strategy, vault)

    assert profit == 0
    if is_migration:
        assert vault.pricePerShare() >= starting_share_price
    else:
        assert vault.pricePerShare() == starting_share_price


# test some gmx-specific functions
def test_gmx_vesting(
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
):
    if not is_gmx:
        return
    elif to_vest == 0:
        strategy.rebalanceVesting({"from": gov})
        return

    # rebalance when we have nothing
    strategy.rebalanceVesting({"from": gov})

    ## deposit to the vault after approving
    starting_whale = token.balanceOf(whale)
    token.approve(vault, 2**256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})

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

    # make sure we are vesting
    assert strategy.vestingEsMpx() > 0

    # rebalance vesting
    strategy.rebalanceVesting({"from": gov})
    assert strategy.vestingEsMpx() > 0

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

    # we shouldn't be able to sweep out more than we have, but it also won't revert
    mpx = interface.IERC20(strategy.mpx())
    before = mpx.balanceOf(gov)
    strategy.unstakeAndSweepVestedMpx(strategy.stakedMpx() * 2, {"from": gov})
    assert before == mpx.balanceOf(gov)

    # sweep out our MPX
    strategy.unstakeAndSweepVestedMpx(strategy.stakedMpx(), {"from": gov})
    assert mpx.balanceOf(gov) > 0


# test redeeming all of our steth, then send in WETH for it after gov sweeps out the NFTs
def test_redeem_all(
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

    # start a redemption
    nft_ids = strategy.pendingWithdrawalRequests()
    assert len(nft_ids) == 0
    assert strategy.pendingRedemptions() == 0
    before_assets = strategy.estimatedTotalAssets()
    print("Assets before initiating withdrawal:", before_assets / 1e18)

    # queue up our withdrawals
    steth = Contract(strategy.stETH())
    weth = Contract(strategy.weth())
    steth_balance = strategy.stethBalance()

    while steth_balance > 1:  # don't get trapped with 1 wei
        to_withdraw = min(1_000e18, steth_balance)
        tx = strategy.initiateLSTWithdrawal(to_withdraw, {"from": gov})
        print("NFT received:", tx.return_value)
        steth_balance = strategy.stethBalance()

    # have a whale send in their weth
    weth_whale = accounts.at("0x57757E3D981446D585Af0D9Ae4d7DF6D64647806", force=True)
    weth.transfer(strategy, strategy.pendingRedemptions(), {"from": weth_whale})

    # have gov sweep out our NFTs
    for x in strategy.pendingWithdrawalRequests():
        strategy.rescueNft(x, {"from": gov})

    assert strategy.pendingRedemptions() == 0
    nft_ids = strategy.pendingWithdrawalRequests()
    assert len(nft_ids) == 0

    # set DebtRatio to 0% and peg to 0 as well
    vault.updateStrategyDebtRatio(strategy, 0, {"from": gov})
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
        assert steth.balanceOf(strategy) <= 1  # sometimes we can't clear all stETH out
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
