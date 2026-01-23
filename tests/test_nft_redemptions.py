from brownie import chain, Contract
from utils import harvest_strategy
import pytest, brownie


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

    # withdraw exactly the same amount as what we're going to steal
    print("\nSend", eth_to_steal / 1e18, "stETH to withdraw")
    tx = strategy.initiateLSTWithdrawal(eth_to_steal, {"from": gov})
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

    # steal the NFT
    nft_owner = withdrawal_status["owner"]
    withdrawal_queue.transferFrom(
        nft_owner, strategy, finalized_nft, {"from": nft_owner}
    )
    assert len(strategy.pendingWithdrawalRequests()) > 1

    # transferring in an NFT won't update our pending redemption state var
    assert strategy.pendingRedemptions() == new_redemptions == eth_to_steal

    # check our assets, we don't count assets that are in our NFT
    new_after_assets = strategy.estimatedTotalAssets()
    assert new_after_assets < before_assets
    print("Assets after transferring in new NFT:", new_after_assets / 1e18)

    # check that permissions work
    with brownie.reverts():
        strategy.claimLSTWithdrawal(finalized_nft, {"from": whale})

    # only do this branch if peg > 0
    if strategy.peg() > 0:
        # store the WETH balance in WETH-1 to make sure it's being sent
        weth_1 = Contract("0xc56413869c6CDf96496f2b1eF801fEDBdFA7dDB0")
        loose_weth = token.balanceOf(weth_1)

        # Have our strategy "lose" lots of stETH so the require fails
        steth = Contract(strategy.stETH())
        before_steth = steth.sharesOf(strategy)
        if before_steth > 0:
            steth.transferShares(gov, before_steth, {"from": strategy})

        # check that our revert hits (will overflow)
        with brownie.reverts():
            strategy.claimLSTWithdrawal(finalized_nft, {"from": gov})

        # send back enough so we don't overflow, but don't send back the peg buffer
        # this should put us close to the limit of the debt our strategy has
        to_send = before_steth - (before_steth * strategy.peg() / 10_000)
        steth.transferShares(strategy, to_send, {"from": gov})

        # bump up the peg value to a higher level to make sure we hit our health check protection
        peg_before = strategy.peg()
        strategy.updatePeg(500, {"from": gov})
        print(
            "Total Assets:",
            strategy.estimatedPotentialTotalAssets() / 1e18,
            "Pending Redemptions:",
            strategy.pendingRedemptions() / 1e18,
            "Debt:",
            vault.strategies(strategy)["totalDebt"] / 1e18,
            "Loose WETH:",
            strategy.wantBalance() / 1e18,
            "Headroom to send:",
            (
                strategy.estimatedPotentialTotalAssets()
                + strategy.pendingRedemptions()
                - vault.strategies(strategy)["totalDebt"]
            )
            / 1e18,
        )
        with brownie.reverts("too high"):
            tx = strategy.claimLSTWithdrawal(finalized_nft, {"from": gov})

        # send it back!
        remainder = before_steth - to_send
        steth.transferShares(strategy, remainder, {"from": gov})
        strategy.updatePeg(peg_before, {"from": gov})

    # withdraw from the stolen NFT
    print("\nWithdraw from the stolen NFT")
    tx = strategy.claimLSTWithdrawal(finalized_nft, {"from": gov})
    print("ETH received:", tx.return_value / 1e18)
    assert tx.return_value == eth_to_steal

    # check if this worked
    assert strategy.pendingRedemptions() == 0

    # again, only for peg
    if strategy.peg() > 0:
        # check how much weth was sent
        sent = token.balanceOf(weth_1) - loose_weth
        print(
            "Sent:",
            sent / 1e18,
            "Expected:",
            eth_to_steal * strategy.peg() / 10_000 / 1e18,
        )

    # withdrawing from the stolen NFT should zero our pending redemptions
    assert strategy.pendingRedemptions() == 0

    # check our assets, make sure we didn't lose anything to peg on the redemption
    final_after_assets = strategy.estimatedTotalAssets()
    assert final_after_assets >= before_assets
    print("Assets after redeeming from new NFT:", final_after_assets / 1e18)
    assert len(strategy.pendingWithdrawalRequests()) == 1

    # have gov pluck out the other NFT
    with brownie.reverts():
        strategy.rescueNft(strategy.pendingWithdrawalRequests()[0], {"from": whale})

    strategy.rescueNft(strategy.pendingWithdrawalRequests()[0], {"from": gov})
    nft_ids = strategy.pendingWithdrawalRequests()
    assert len(nft_ids) == 0

    # rescuing NFT should leave this at zero since it's already there
    assert strategy.pendingRedemptions() == 0


# test big redemptions with multiple NFTs
def test_big_redeems(
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

    # find some sucker with ETH to steal
    withdrawal_queue = Contract("0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1")
    finalized_nft = withdrawal_queue.getLastFinalizedRequestId()
    eth_to_steal = 0
    print("\nSteal an NFT with at least 100 ETH finalized but not claimed")
    # check the withdrawal queue's finalized NFTs, finds the first with decent steth, and transfers it into strategy. start with last finalized request
    amounts_to_steal = []
    nft_ids_to_steal = []
    check_count = 0
    while len(amounts_to_steal) < 2:
        withdrawal_status = withdrawal_queue.getWithdrawalStatus([finalized_nft])[0]
        assert withdrawal_status["isFinalized"]
        eth_to_steal = 0
        if not withdrawal_status["isClaimed"]:
            eth_to_steal = withdrawal_status["amountOfStETH"]
        if eth_to_steal < 100e18:
            finalized_nft -= 1
        else:
            print(
                "Found a good NFT:",
                finalized_nft,
                "With this much ETH:",
                eth_to_steal / 1e18,
            )
            amounts_to_steal.append(eth_to_steal)
            nft_ids_to_steal.append(finalized_nft)
            finalized_nft -= 1
        check_count += 1
        if check_count % 25 == 0:
            print("Checked", check_count, "withdrawals so far")

    # withdraw exactly the same amount as what we're going to steal
    for x in amounts_to_steal:
        eth_to_steal = x
        print("\nSend", eth_to_steal / 1e18, "stETH to withdraw")
        tx = strategy.initiateLSTWithdrawal(eth_to_steal, {"from": gov})
        assert strategy.pendingRedemptions() > 0
        new_redemptions = strategy.pendingRedemptions()
        print("NFT received:", tx.return_value)
        after_assets = strategy.estimatedTotalAssets()
        assert after_assets < before_assets
        print("Assets after initiating withdrawal:", after_assets / 1e18)

    # check that we have NFTs
    nft_ids = strategy.pendingWithdrawalRequests()
    assert len(nft_ids) == 2
    print("Withdrawal IDs:", nft_ids)

    # steal the NFTs
    for x in nft_ids_to_steal:
        nft_owner = withdrawal_queue.getWithdrawalStatus([x])[0]["owner"]
        withdrawal_queue.transferFrom(nft_owner, strategy, x, {"from": nft_owner})

    # this should update if we happen to transfer in random NFTs
    assert len(strategy.pendingWithdrawalRequests()) > 3

    # transferring in an NFT won't update our pending redemption state var
    assert strategy.pendingRedemptions() == new_redemptions

    # check our assets, we don't count assets that are in our NFT
    new_after_assets = strategy.estimatedTotalAssets()
    assert new_after_assets < before_assets
    print("Assets after transferring in new NFT:", new_after_assets / 1e18)

    # do some manual divesting here
    strategy.updateMaxSingleTrade(500e18, {"from": gov})
    before_steth = strategy.stethBalance()
    strategy.manualDivest(5_000_000e18, {"from": gov})  # check that our limiting works
    assert (
        abs((before_steth - 500e18) - strategy.stethBalance()) == 1
    )  # approximate because of stETH rounding issues, and pytest.approx breaks with big ints
    assets_after_divest = strategy.estimatedTotalAssets()
    assert assets_after_divest > new_after_assets
    print("Assets after manually divesting 500 ETH:", assets_after_divest / 1e18)

    # only do this branch if peg > 0
    if strategy.peg() > 0:
        # store the WETH balance in WETH-1 to make sure it's being sent
        weth_1 = Contract("0xc56413869c6CDf96496f2b1eF801fEDBdFA7dDB0")
        loose_weth = token.balanceOf(weth_1)

        # Have our strategy "lose" lots of stETH so the require fails
        steth = Contract(strategy.stETH())
        before_steth = steth.sharesOf(strategy)
        if before_steth > 0:
            steth.transferShares(gov, before_steth, {"from": strategy})

        # check that our revert hits (will overflow)
        with brownie.reverts():
            strategy.claimLSTWithdrawal(nft_ids_to_steal[0], {"from": gov})

        # send back enough so we don't overflow, but don't send back the peg buffer
        # this should put us close to the limit of the debt our strategy has
        to_send = before_steth - (before_steth * strategy.peg() / 10_000)
        steth.transferShares(strategy, to_send, {"from": gov})

        # bump up the peg value to a higher level to make sure we hit our health check protection
        peg_before = strategy.peg()
        strategy.updatePeg(500, {"from": gov})
        print(
            "Total Assets:",
            strategy.estimatedPotentialTotalAssets() / 1e18,
            "Pending Redemptions:",
            strategy.pendingRedemptions() / 1e18,
            "Debt:",
            vault.strategies(strategy)["totalDebt"] / 1e18,
            "Loose WETH:",
            strategy.wantBalance() / 1e18,
            "Headroom to send:",
            (
                strategy.estimatedPotentialTotalAssets()
                + strategy.pendingRedemptions()
                - vault.strategies(strategy)["totalDebt"]
            )
            / 1e18,
        )
        with brownie.reverts("too high"):
            tx = strategy.claimLSTWithdrawal(nft_ids_to_steal[0], {"from": gov})

        # send it back!
        remainder = before_steth - to_send
        steth.transferShares(strategy, remainder, {"from": gov})
        strategy.updatePeg(peg_before, {"from": gov})

    # withdraw from the stolen NFTs
    for x in nft_ids_to_steal:
        print("\nWithdraw from the stolen NFT")
        tx = strategy.claimLSTWithdrawal(x, {"from": gov})
        print("ETH received:", tx.return_value / 1e18)
        assert tx.return_value == amounts_to_steal[nft_ids_to_steal.index(x)]

    # check if this is already zeroed out (since sometimes stETH transfers leave dust), withdrawing from the stolen NFT should zero our pending redemptions
    assert strategy.pendingRedemptions() == 0

    # again, only for peg
    if strategy.peg() > 0:
        # check how much weth was sent
        sent = token.balanceOf(weth_1) - loose_weth
        print(
            "Sent:",
            sent / 1e18,
            "Expected:",
            eth_to_steal * strategy.peg() / 10_000 / 1e18,
        )

    # check our assets, make sure we didn't lose anything to peg on the redemption
    final_after_assets = strategy.estimatedTotalAssets()
    assert final_after_assets >= before_assets
    print("Assets after redeeming from new NFT:", final_after_assets / 1e18)
    assert len(strategy.pendingWithdrawalRequests()) == 2

    strategy.rescueNft(strategy.pendingWithdrawalRequests()[0], {"from": gov})
    nft_ids = strategy.pendingWithdrawalRequests()
    assert len(nft_ids) == 1
    strategy.rescueNft(strategy.pendingWithdrawalRequests()[0], {"from": gov})
    nft_ids = strategy.pendingWithdrawalRequests()
    assert len(nft_ids) == 0

    # rescuing NFT should leave this at zero since it's already there
    assert strategy.pendingRedemptions() == 0


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
