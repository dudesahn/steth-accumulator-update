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

    # withdraw and confirm we made money, or at least that we have about the same
    vault.withdraw({"from": whale})
    if no_profit:
        assert (
            pytest.approx(token.balanceOf(whale), rel=RELATIVE_APPROX) == starting_whale
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
