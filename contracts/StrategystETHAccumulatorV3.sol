// SPDX-License-Identifier: AGPL-3.0
pragma solidity 0.8.28;

import {BaseStrategy, StrategyParams, SafeERC20, IERC20} from "@yearnvaults/contracts/BaseStrategy.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

import {ISteth, IQueue, IWETH, ICurveFi} from "./interfaces/StethInterfaces.sol";

contract StrategystETHAccumulatorV3 is BaseStrategy {
    using SafeERC20 for IERC20;

    event WithdrawalLoss(uint256 toWithdraw, uint256 received, uint256 loss);

    bool public checkLiqGauge = true;
    ICurveFi public constant StableSwapSTETH =
        ICurveFi(0xDC24316b9AE028F1497c275EB9192a3Ea0f67022);
    IWETH public constant weth =
        IWETH(0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2);
    ISteth public constant stETH =
        ISteth(0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84);

    address private referal = 0x16388463d60FFE0661Cf7F1f31a7D658aC790ff7; //stratms. for recycling and redepositing
    uint256 public maxSingleTrade;
    uint256 public constant DENOMINATOR = 10_000;
    uint256 public slippageProtectionOut; // = 50; //out of 10000. 50 = 0.5%

    uint256 public pendingRedemptions;

    bool public reportLoss = false;
    bool public dontInvest = true;

    uint256 public peg = 95; // 100 = 1%

    // stETH specific constants
    address internal constant WITHDRAWAL_QUEUE =
        0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1; // stETH withdrawal queue

    int128 internal constant WETHID = 0;
    int128 internal constant STETHID = 1;

    constructor(address _vault) BaseStrategy(_vault) {
        // You can set these parameters on deployment to whatever you want
        maxReportDelay = 1 weeks;
        healthCheck = 0xDDCea799fF1699e98EDF118e0629A974Df7DF012; // hardcode healthcheck

        stETH.approve(address(StableSwapSTETH), type(uint256).max);

        maxSingleTrade = 500 * 1e18;
        slippageProtectionOut = 50;
    }

    //we get eth
    receive() external payable {}

    function updateReferal(address _referal) external onlyEmergencyAuthorized {
        referal = _referal;
    }

    function updateMaxSingleTrade(uint256 _maxSingleTrade)
        external
        onlyVaultManagers
    {
        maxSingleTrade = _maxSingleTrade;
    }

    function updatePeg(uint256 _peg) external onlyVaultManagers {
        require(_peg <= 1_000); //limit peg to max 10%
        peg = _peg;
    }

    function updateReportLoss(bool _reportLoss) external onlyVaultManagers {
        reportLoss = _reportLoss;
    }

    function updateDontInvest(bool _dontInvest) external onlyVaultManagers {
        dontInvest = _dontInvest;
    }

    function updateSlippageProtectionOut(uint256 _slippageProtectionOut)
        external
        onlyVaultManagers
    {
        require(_slippageProtectionOut <= 10_000);
        slippageProtectionOut = _slippageProtectionOut;
    }

    function invest(uint256 _amount) external onlyEmergencyAuthorized {
        _invest(_amount);
    }

    //should never have stuck eth but just incase
    function rescueStuckEth() external onlyEmergencyAuthorized {
        weth.deposit{value: address(this).balance}();
    }

    function name() external view override returns (string memory) {
        // Add your own name here, suggestion e.g. "StrategyCreamYFI"
        return "StrategystETHAccumulator_v3";
    }

    // We hard code a peg here. This is so that we can build up a reserve of profit to cover peg volatility if we are forced to delever
    // This may sound scary but it is the equivalent of using virtualprice in a curve lp. As we have seen from many exploits, virtual pricing is safer than touch pricing.
    function estimatedTotalAssets() public view override returns (uint256) {
        return
            ((stethBalance() * (DENOMINATOR - peg)) / DENOMINATOR) +
            wantBalance();
    }

    function estimatedPotentialTotalAssets() public view returns (uint256) {
        return stethBalance() + wantBalance();
    }

    function wantBalance() public view returns (uint256) {
        return want.balanceOf(address(this));
    }

    function stethBalance() public view returns (uint256) {
        return stETH.balanceOf(address(this));
    }

    function prepareReturn(uint256 _debtOutstanding)
        internal
        override
        returns (
            uint256 _profit,
            uint256 _loss,
            uint256 _debtPayment
        )
    {
        uint256 wantBal = wantBalance();
        uint256 totalAssets = estimatedTotalAssets();

        uint256 debt = vault.strategies(address(this)).totalDebt;

        if (totalAssets >= debt) {
            _profit = totalAssets - debt;

            uint256 toWithdraw = _profit + _debtOutstanding;

            if (toWithdraw > wantBal) {
                toWithdraw = Math.min(toWithdraw, stethBalance());
                uint256 willWithdraw = Math.min(maxSingleTrade, toWithdraw);
                uint256 withdrawn = _divest(willWithdraw); //we step our withdrawals. adjust max single trade to withdraw more
                // assume that we get peg level of slippage on our withdrawal
                if (withdrawn < willWithdraw) {
                    // _loss = willWithdraw - withdrawn; // comment this and the line below out to skip taking losses on harvest withdrawals
                    emit WithdrawalLoss(willWithdraw, withdrawn, _loss); // ****ONLY FOR TESTING REMOVE BEFORE DEPLOY
                }
                // check in on our new amount of tokens after withdrawing
                // loss on divesting is only a true loss if it's bigger than our peg value
                wantBal = wantBalance();
                totalAssets = estimatedTotalAssets();
                // redo our check for profit now that we've swapped stETH for WETH
                if (totalAssets > debt) {
                    _profit = totalAssets - debt;
                } else {
                    _loss = debt - totalAssets;
                }
            }

            // profit + _debtOutstanding must be <= wantbalance. Prioritise profit first
            if (wantBal < _profit) {
                _profit = wantBal;
            } else if (wantBal < toWithdraw) {
                // we will likely hit this if we reducing debt via swaps since we get some slippage
                _debtPayment = wantBal - _profit;
            } else {
                _debtPayment = _debtOutstanding;
            }
        } else {
            if (reportLoss) {
                _loss = debt - totalAssets;
            }
        }
    }

    function ethToWant(uint256 _amtInWei)
        public
        view
        override
        returns (uint256)
    {
        return _amtInWei;
    }

    function liquidateAllPositions()
        internal
        override
        returns (uint256 _amountFreed)
    {
        _divest(stethBalance());
        _amountFreed = wantBalance();
    }

    function adjustPosition(uint256 _debtOutstanding) internal override {
        if (dontInvest) {
            return;
        }
        _invest(wantBalance());
    }

    function _invest(uint256 _amount) internal returns (uint256) {
        if (_amount == 0) {
            return 0;
        }

        _amount = Math.min(maxSingleTrade, _amount);
        uint256 before = stethBalance();

        weth.withdraw(_amount);

        //test if we should buy instead of mint
        uint256 out = StableSwapSTETH.get_dy(WETHID, STETHID, _amount);
        if (out < _amount) {
            stETH.submit{value: _amount}(referal);
        } else {
            StableSwapSTETH.exchange{value: _amount}(
                WETHID,
                STETHID,
                _amount,
                _amount
            );
        }

        return stethBalance() - before;
    }

    function _divest(uint256 _amount) internal returns (uint256) {
        uint256 before = wantBalance();

        if (_amount > 0) {
            uint256 slippageAllowance = (_amount *
                (DENOMINATOR - slippageProtectionOut)) / DENOMINATOR;
            StableSwapSTETH.exchange(
                STETHID,
                WETHID,
                _amount,
                slippageAllowance
            );

            weth.deposit{value: address(this).balance}();
        }

        return wantBalance() - before;
    }

    // we attempt to withdraw the full amount and let the user decide if they take the loss or not
    function liquidatePosition(uint256 _amountNeeded)
        internal
        override
        returns (uint256 _liquidatedAmount, uint256 _loss)
    {
        uint256 wantBal = wantBalance();
        if (wantBal < _amountNeeded) {
            uint256 toWithdraw = _amountNeeded - wantBal;
            uint256 withdrawn = _divest(toWithdraw);
            if (withdrawn < toWithdraw) {
                _loss = toWithdraw - withdrawn;
            }
        }

        _liquidatedAmount = _amountNeeded - _loss;
    }

    function prepareMigration(address _newStrategy) internal override {
        uint256 stethBal = stethBalance();
        if (stethBal > 0) {
            stETH.transfer(_newStrategy, stethBal);
        }
    }

    // Override this to add all tokens/tokenized positions this contract manages
    // on a *persistent* basis (e.g. not just for swapping back to want ephemerally)
    // NOTE: Do *not* include `want`, already included in `sweep` below
    //
    // Example:
    //
    //    function protectedTokens() internal override view returns (address[] memory) {
    //      address[] memory protected = new address[](3);
    //      protected[0] = tokenA;
    //      protected[1] = tokenB;
    //      protected[2] = tokenC;
    //      return protected;
    //    }
    function protectedTokens()
        internal
        view
        override
        returns (address[] memory)
    {}

    /// @notice Initiate stETH withdrawal through Lido queue for 1:1 redemption
    /// @param _amount Amount of LST to queue for withdrawal
    /// @return returnData Return data from the withdrawal request
    function initiateLSTWithdrawal(uint256 _amount)
        external
        onlyEmergencyAuthorized
        returns (bytes memory returnData)
    {
        _amount = Math.min(_amount, stethBalance());
        require(_amount > 100, "!minimum"); // minimum amount to withdraw
        require(_amount <= 1_000e18, "!minimum"); // maximum amount to withdraw in one request
        pendingRedemptions += _amount;
        return _initiateLSTWithdrawal(_amount);
    }

    /// @notice Claim ETH from completed Lido withdrawal request
    /// @param _claimData The claim data from the withdrawal request
    /// @return _amount Amount of LST claimed
    function claimLSTWithdrawal(bytes memory _claimData)
        external
        onlyEmergencyAuthorized
        returns (uint256)
    {
        uint256 _redeemedAmount = _claimLSTWithdrawal(_claimData);
        pendingRedemptions = _redeemedAmount >= pendingRedemptions
            ? 0
            : pendingRedemptions - _redeemedAmount;
        return _redeemedAmount;
    }

    /// @notice Initiate stETH withdrawal through Lido queue for 1:1 redemption
    /// @param _amount Amount of LST to queue for withdrawal
    /// @return returnData Return data from the withdrawal request
    function _initiateLSTWithdrawal(uint256 _amount)
        internal
        returns (bytes memory returnData)
    {
        IERC20(address(stETH)).safeApprove(WITHDRAWAL_QUEUE, _amount);

        uint256[] memory _amounts = new uint256[](1);
        _amounts[0] = _amount;

        uint256[] memory requestIds = IQueue(WITHDRAWAL_QUEUE)
            .requestWithdrawals(_amounts, address(this));

        return abi.encode(requestIds);
    }

    /// @notice Claim ETH from completed Lido withdrawal request
    /// @param _claimData The claim data from the withdrawal request
    function _claimLSTWithdrawal(bytes memory _claimData)
        internal
        returns (uint256 _redeemedAmount)
    {
        uint256 _requestId = abi.decode(_claimData, (uint256));

        uint256 preBalance = address(this).balance;
        IQueue(WITHDRAWAL_QUEUE).claimWithdrawal(_requestId);
        _redeemedAmount = address(this).balance - preBalance;

        // Convert received ETH to WETH
        IWETH(address(want)).deposit{value: address(this).balance}();
    }

    /// @notice Rescue a stuck withdrawal NFT. Only may be called by governance.
    function rescueNft(uint256 _requestId) external onlyGovernance {
        IQueue(WITHDRAWAL_QUEUE).safeTransferFrom(
            address(this),
            governance(),
            _requestId
        );
    }
}
