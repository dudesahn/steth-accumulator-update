import pytest
from brownie import config, ZERO_ADDRESS, chain, interface, accounts, Contract
import requests


@pytest.fixture(scope="function", autouse=True)
def isolate(fn_isolation):
    pass


# set this for if we want to use tenderly or not; mostly helpful because with brownie.reverts fails in tenderly forks.
use_tenderly = False

# use this to set what chain we use. 1 for ETH, 250 for fantom, 10 optimism, 42161 arbitrum
chain_used = 1


################################################## TENDERLY DEBUGGING ##################################################


# change autouse to True if we want to use this fork to help debug tests
@pytest.fixture(scope="session", autouse=use_tenderly)
def tenderly_fork(web3, chain):
    fork_base_url = "https://simulate.yearn.network/fork"
    payload = {"network_id": str(chain.id)}
    resp = requests.post(fork_base_url, headers={}, json=payload)
    fork_id = resp.json()["simulation_fork"]["id"]
    fork_rpc_url = f"https://rpc.tenderly.co/fork/{fork_id}"
    print(fork_rpc_url)
    tenderly_provider = web3.HTTPProvider(fork_rpc_url, {"timeout": 600})
    web3.provider = tenderly_provider
    print(f"https://dashboard.tenderly.co/yearn/yearn-web/fork/{fork_id}")


################################################ UPDATE THINGS BELOW HERE ################################################

#################### FIXTURES BELOW NEED TO BE ADJUSTED FOR THIS REPO ####################


@pytest.fixture(scope="session")
def token():
    token_address = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    yield interface.IERC20(token_address)


@pytest.fixture(scope="session")
def whale(amount, token, use_v3):
    # Totally in it for the tech
    # Update this with a large holder of your want token (the largest EOA holder of LP)
    whale = accounts.at(
        "0x8EB8a3b98659Cce290402893d0123abb75E3ab28", force=True
    )  # 0x8EB8a3b98659Cce290402893d0123abb75E3ab28, AVAX Bridge, 34k WETH
    if token.balanceOf(whale) < 2 * amount:
        raise ValueError(
            "Our whale needs more funds. Find another whale or reduce your amount variable."
        )
    yield whale


@pytest.fixture(scope="session")
def amount(token):
    amount = 1_000 * 10 ** token.decimals()
    yield amount


@pytest.fixture(scope="session")
def profit_whale(profit_amount, token, use_v3):
    # ideally not the same whale as the main whale, or else they will lose money
    profit_whale = accounts.at(
        "0x57757E3D981446D585Af0D9Ae4d7DF6D64647806", force=True
    )  # 0x57757E3D981446D585Af0D9Ae4d7DF6D64647806, poap guy, 19k WETH
    if token.balanceOf(profit_whale) < 5 * profit_amount:
        raise ValueError(
            "Our profit whale needs more funds. Find another whale or reduce your profit_amount variable."
        )
    yield profit_whale


@pytest.fixture(scope="session")
def profit_amount(token):
    # make this large enough so it will cover any slippage loss on exiting out with peg set to 0
    profit_amount = 7.5 * 10 ** token.decimals()
    yield profit_amount


# set address if already deployed, use ZERO_ADDRESS if not
@pytest.fixture(scope="session")
def vault_address():
    vault_address = "0xa258C4606Ca8206D8aA700cE2143D7db854D168c"
    yield vault_address


# if our vault is pre-0.4.3, this will affect a few things
@pytest.fixture(scope="session")
def old_vault():
    old_vault = True
    yield old_vault


# this is the name we want to give our strategy
@pytest.fixture(scope="session")
def strategy_name():
    strategy_name = "StrategyRouterV2"
    yield strategy_name


# this is the name of our strategy in the .sol file
@pytest.fixture(scope="session")
def contract_name(
    StrategystETHAccumulatorV3,
):
    contract_name = StrategystETHAccumulatorV3
    yield contract_name


# if our strategy is using ySwaps, then we need to donate profit to it from our profit whale
@pytest.fixture(scope="session")
def use_yswaps():
    use_yswaps = False
    yield use_yswaps


# whether or not a strategy is clonable. if true, don't forget to update what our cloning function is called in test_cloning.py
@pytest.fixture(scope="session")
def is_clonable():
    is_clonable = False
    yield is_clonable


# use this to test our strategy in case there are no profits
@pytest.fixture(scope="session")
def no_profit():
    no_profit = False
    yield no_profit


# use this when we might lose a few wei on conversions between want and another deposit token (like router strategies)
# generally this will always be true if no_profit is true, even for curve/convex since we can lose a wei converting
@pytest.fixture(scope="session")
def is_slippery(no_profit):
    is_slippery = True  # set this to true or false as needed
    if no_profit:
        is_slippery = True
    yield is_slippery


# use this to set the standard amount of time we sleep between harvests.
# generally 1 day, but can be less if dealing with smaller windows (oracles) or longer if we need to trigger weekly earnings.
@pytest.fixture(scope="session")
def sleep_time():
    hour = 3600

    # change this one right here
    hours_to_sleep = 24

    sleep_time = hour * hours_to_sleep
    yield sleep_time


#################### FIXTURES ABOVE NEED TO BE ADJUSTED FOR THIS REPO ####################

#################### FIXTURES BELOW SHOULDN'T NEED TO BE ADJUSTED FOR THIS REPO ####################


@pytest.fixture(scope="session")
def tests_using_tenderly():
    yes_or_no = use_tenderly
    yield yes_or_no


# by default, pytest uses decimals, but in solidity we use uints, so 10 actually equals 10 wei (1e-17 for most assets, or 1e-6 for USDC/USDT)
@pytest.fixture(scope="session")
def RELATIVE_APPROX(token):
    approx = 10
    print("Approx:", approx, "wei")
    yield approx


# use this to set various fixtures that differ by chain
if chain_used == 1:  # mainnet

    @pytest.fixture(scope="session")
    def gov():
        yield accounts.at("0xFEB4acf3df3cDEA7399794D0869ef76A6EfAff52", force=True)

    @pytest.fixture(scope="session")
    def health_check():
        yield interface.IHealthCheck("0xddcea799ff1699e98edf118e0629a974df7df012")

    @pytest.fixture(scope="session")
    def base_fee_oracle():
        yield interface.IBaseFeeOracle("0xfeCA6895DcF50d6350ad0b5A8232CF657C316dA7")

    # set all of the following to SMS, just simpler
    @pytest.fixture(scope="session")
    def management():
        yield accounts.at("0x16388463d60FFE0661Cf7F1f31a7D658aC790ff7", force=True)

    @pytest.fixture(scope="session")
    def rewards(management):
        yield management

    @pytest.fixture(scope="session")
    def guardian(management):
        yield management

    @pytest.fixture(scope="session")
    def strategist(management):
        yield management

    @pytest.fixture(scope="session")
    def keeper(management):
        yield management

    @pytest.fixture(scope="session")
    def to_sweep():
        # token we can sweep out of strategy (use CRV)
        yield interface.IERC20("0xD533a949740bb3306d119CC777fa900bA034cd52")

    @pytest.fixture(scope="session")
    def trade_factory():
        yield interface.ITradeHandler("0xcADBA199F3AC26F67f660C89d43eB1820b7f7a3b")

    @pytest.fixture(scope="session")
    def keeper_wrapper():
        yield interface.IFactoryKeeperWrapper(
            "0x0D26E894C2371AB6D20d99A65E991775e3b5CAd7"
        )


@pytest.fixture(scope="module")
def vault(pm, gov, rewards, guardian, management, token, vault_address):
    if vault_address == ZERO_ADDRESS:
        Vault = pm(config["dependencies"][0]).Vault
        vault = guardian.deploy(Vault)
        vault.initialize(token, gov, rewards, "", "", guardian)
        vault.setDepositLimit(2**256 - 1, {"from": gov})
        vault.setManagement(management, {"from": gov})
    else:
        vault = interface.IVaultFactory045(vault_address)
    if vault.performanceFee() != 0:
        vault.setPerformanceFee(0, {"from": gov})
    if vault.managementFee() != 0:
        vault.setManagementFee(0, {"from": gov})
    yield vault


#################### FIXTURES ABOVE SHOULDN'T NEED TO BE ADJUSTED FOR THIS REPO ####################

#################### FIXTURES BELOW LIKELY NEED TO BE ADJUSTED FOR THIS REPO ####################


@pytest.fixture(scope="session")
def target(destination_strategy):
    # whatever we want it to be—this is passed into our harvest function as a target
    yield destination_strategy


# this should be a strategy from a different vault to check during migration
@pytest.fixture(scope="session")
def other_strategy():
    yield Contract("0x307Dd52c310e8a5253CBF1FfE5149487d18866eE")


@pytest.fixture
def strategy(
    strategist,
    keeper,
    vault,
    gov,
    management,
    health_check,
    contract_name,
    strategy_name,
    base_fee_oracle,
    vault_address,
    trade_factory,
    destination_vault,
    token,
    invest_all_first,
    leave_on_invest,
    dont_report_loss,
):
    # will need to update this based on the strategy's constructor ******
    strategy = gov.deploy(contract_name, vault)

    # strategy.setKeeper(keeper, {"from": gov})
    # strategy.setHealthCheck(health_check, {"from": gov})
    # strategy.setDoHealthCheck(True, {"from": gov})

    steth = Contract(strategy.stETH())

    # run tests with all funds invested as well as with some loose WETH in the strategy (default)
    old_accumulator = vault.withdrawalQueue(1)
    old_strategy = Contract(old_accumulator)
    if invest_all_first:
        # update to invest
        old_strategy.updateDontInvest(False, {"from": management})
        assert old_strategy.wantBalance() > 0

        # invest
        old_strategy.harvest({"from": management})
        assert old_strategy.wantBalance() == 0
        chain.sleep(60)
        chain.mine()

    #         # account for our "losses"
    #         old_strategy.setDoHealthCheck(False, {"from": gov})
    #         tx = old_strategy.harvest({"from": management})
    #         loss = tx.events["Harvested"]["loss"]
    #         print("\n😭 Loss from investing:", loss / 1e18, "WETH\n")
    #         chain.sleep(60)
    #         chain.mine()
    #
    #         # turn it back off once we've finished
    #         strategy.updateDontInvest(True, {"from": management})

    # migrate to our new strategy to inherit the broken state
    print(
        "Strategy loose want before migration:", token.balanceOf(old_accumulator) / 1e18
    )
    print(
        "Old strategy stETH before migration:", steth.balanceOf(old_accumulator) / 1e18
    )
    print("Vault balance of want before migration:", token.balanceOf(vault) / 1e18)
    vault.migrateStrategy(old_accumulator, strategy, {"from": gov})
    print(
        "Old strategy loose want after migration:",
        token.balanceOf(old_accumulator) / 1e18,
    )
    print("New strategy loose want after migration:", token.balanceOf(strategy) / 1e18)
    print("Vault balance of want after migration:", token.balanceOf(vault) / 1e18)
    print("New strategy stETH after migration:", steth.balanceOf(strategy) / 1e18)

    # for stETH accumulator, turn off our limit on max to swap at once for several of our debt tests
    strategy.updateMaxSingleTrade(1_000_000e18, {"from": gov})

    # update our slippage higher since we're exiting a large chunk of the pool in some tests (with no arb)
    strategy.updateSlippageProtectionOut(150, {"from": gov})

    # turn on health check for first harvest since we're inheriting profit
    # strategy.setDoHealthCheck(False, {"from": gov})

    # if we have other strategies, set them to zero DR and remove them from the queue
    if vault_address != ZERO_ADDRESS:
        for i in range(0, 20):
            strat_address = vault.withdrawalQueue(i)
            if ZERO_ADDRESS == strat_address:
                break

            if strat_address == strategy.address:
                continue

            if vault.strategies(strat_address)["debtRatio"] > 0:
                vault.updateStrategyDebtRatio(strat_address, 0, {"from": gov})
                # as of 11/20, this results in ~2200 WETH moving from the router to the vault
                interface.ICurveStrategy045(strat_address).harvest({"from": gov})
                vault.removeStrategyFromQueue(strat_address, {"from": gov})

    # set debt ratio to 100% on accumulator
    vault.updateStrategyDebtRatio(strategy, 10_000, {"from": gov})

    # turn our oracle into testing mode by setting the provider to 0x00, then forcing true
    strategy.setBaseFeeOracle(base_fee_oracle, {"from": management})
    base_fee_oracle.setBaseFeeProvider(ZERO_ADDRESS, {"from": management})
    base_fee_oracle.setManualBaseFeeBool(True, {"from": management})
    assert strategy.isBaseFeeAcceptable() == True

    if invest_all_first:
        assert strategy.wantBalance() == 0
        # keep investing
        if leave_on_invest:
            strategy.updateDontInvest(False, {"from": management})
            # turn off loss reporting if we're investing again too since we automatically lose peg() on each invest
            if dont_report_loss:
                strategy.updateReportLoss(False, {"from": management})
            # also set peg to 0 to minimize losses reported that break a lot of test assumptions
            strategy.updatePeg(0, {"from": gov})

    yield strategy


#################### FIXTURES ABOVE LIKELY NEED TO BE ADJUSTED FOR THIS REPO ####################

####################         PUT UNIQUE FIXTURES FOR THIS REPO BELOW         ####################


# test out leaving on investing all loose WETH to stETH
@pytest.fixture(scope="session")
def leave_on_invest(invest_all_first):
    if not invest_all_first:
        leave_on = False
    else:
        leave_on = True  # adjust this one as needed
    yield leave_on


# test out depositing all of our loose WETH to stETH first
@pytest.fixture(scope="session")
def invest_all_first():
    yield True


# set to true if we should avoid reporting losses on harvests
@pytest.fixture(scope="session")
def dont_report_loss():
    yield False


# tried parameterizing these two but brownie did not seem to like it and started locking up
# use this for whether we want to test the old version of the strategy
@pytest.fixture(scope="session")
def use_old():
    yield False


# use this if we're doing a V2 or V3 router
@pytest.fixture(scope="session")
def use_v3():
    yield False


# flag to denote if we're migrating from existing strategies and thus will likely have profit on our first harvest
@pytest.fixture(scope="session")
def is_migration():
    yield True


# use this similarly to how we use use_yswaps
@pytest.fixture(scope="session")
def is_gmx():
    yield False


# use this similarly to how we use use_yswaps
@pytest.fixture(scope="session")
def is_router():
    yield False


@pytest.fixture(scope="session")
def destination_vault(use_v3):
    # destination vault of the route.
    if use_v3:
        yield Contract("0x028eC7330ff87667b6dfb0D94b954c820195336c")
    else:
        yield interface.IVaultFactory045("0x63bD3Bbb6c5cb6E457C3f3cbb2D8aa2536E319F1")


@pytest.fixture(scope="session")
def destination_strategy(destination_vault, use_v3):
    # destination curve strategy of the route
    if use_v3:
        yield Contract("0xAeDF7d5F3112552E110e5f9D08c9997Adce0b78d")
    else:
        yield interface.ICurveStrategy045(destination_vault.withdrawalQueue(1))
