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


# test a realistic flow of slowly winding down the strategy with the core migration, harvests and redemptions
def test_migrate_harvest_redeem(
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

    # check that permissions work
    with brownie.reverts():
        strategy.initiateLSTWithdrawal(10e18, {"from": whale})

    print("\nSend 10 stETH to withdraw")
    tx = strategy.initiateLSTWithdrawal(10e18, {"from": gov})
    assert strategy.pendingRedemptions() > 0
    new_redemptions = strategy.pendingRedemptions()
    print("NFT received:", tx.return_value)
    after_assets = strategy.estimatedTotalAssets()
    assert after_assets < before_assets
    print("Assets after initiating withdrawal:", after_assets / 1e18)

    # check that we have an NFT
    nft_ids = strategy.pendingWithdrawalRequests()
    assert len(nft_ids) == 1
    print("Withdrawal ID:", nft_ids)

    # find some sucker with ETH to steal
    withdrawal_queue = Contract("0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1")
    finalized_nft = withdrawal_queue.getLastFinalizedRequestId()
    eth_to_steal = 0
    print("\nSteal an NFT with at least 10 ETH finalized but not claimed")
    # check the withdrawal queue's finalized NFTs, finds the first with decent steth, and transfers it into strategy. start with last finalized request
    while eth_to_steal < 10e18:
        withdrawal_status = withdrawal_queue.getWithdrawalStatus([finalized_nft])[0]
        assert withdrawal_status["isFinalized"]
        if not withdrawal_status["isClaimed"]:
            eth_to_steal = withdrawal_status["amountOfStETH"]
        if eth_to_steal < 10e18:
            finalized_nft -= 1
        else:
            print(
                "Found a good NFT:",
                finalized_nft,
                "With this much ETH:",
                eth_to_steal / 1e18,
            )

    # steal the NFT
    nft_owner = withdrawal_status["owner"]
    withdrawal_queue.transferFrom(
        nft_owner, strategy, finalized_nft, {"from": nft_owner}
    )
    assert len(strategy.pendingWithdrawalRequests()) > 1

    # transferring in an NFT won't update our pending redemption state var
    assert strategy.pendingRedemptions() == new_redemptions

    # check our assets
    after_assets = strategy.estimatedTotalAssets()
    assert after_assets < before_assets
    print("Assets after transferring in new NFT:", after_assets / 1e18)

    # check that permissions work
    with brownie.reverts():
        strategy.claimLSTWithdrawal(finalized_nft, {"from": whale})

    # withdraw from the stolen NFT
    print("\nWithdraw from the stolen NFT")
    tx = strategy.claimLSTWithdrawal(finalized_nft, {"from": gov})
    print("ETH received:", tx.return_value / 1e18)
    assert tx.return_value == eth_to_steal

    # withdrawing from the stolen NFT should zero our pending redemptions
    assert strategy.pendingRedemptions() == 0

    # check our assets
    after_assets = strategy.estimatedTotalAssets()
    assert after_assets >= before_assets
    print("Assets after transferring in new NFT:", after_assets / 1e18)
    assert len(strategy.pendingWithdrawalRequests()) == 1

    # have gov pluck out the other NFT
    with brownie.reverts():
        strategy.rescueNft(strategy.pendingWithdrawalRequests()[0], {"from": whale})

    strategy.rescueNft(strategy.pendingWithdrawalRequests()[0], {"from": gov})
    nft_ids = strategy.pendingWithdrawalRequests()
    assert len(nft_ids) == 0

    # rescuing NFT should leave this at zero since it's already there
    assert strategy.pendingRedemptions() == 0


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

    # set peg to zero so we properly account for all funds
    strategy.updatePeg(0, {"from": gov})

    # We are failing in `vault.report()` to actually have all of the WETH that we think we have in profit…some of it is staying trapped as stETH and thus we revert.
    # our debtOutstanding going into the report below is: 12425736071706193190121

    # one option could be to just set peg to zero before we do a final report that empties everything out, in case we're going from full strategy to nothing
    # also consider changing the ordering to not prioritize profit and to instead prioritize returning debt...would leave us with profits at the very end and no debt probably?

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
