## Testing for new routers

- V2 => V3 fixes previous issues with rounding on setting debtRatio to 0 (or revoking) and harvesting
- V2 => V2 fixes previous issues with rounding on withdrawal and trying to deposit in adjustPosition with only 1 wei
- updated tests to compare old and new versions of both strategies
- split some out into multiple tests because of anvil dying when too many txns in a fork.
- for V2 => V2 router, `brownie test -s` still plays nice with ganache and speeds things up considerably, but for V2 => V3 anvil is required.

```python
# V2 new, v3 new, v3 old, v2 old
brownie test tests/test_change_debt.py -s # ✅✅ 🚫✅ # old V3 fails on debtRatio == 0 + harvest
brownie test tests/test_cloning.py -s # ✅✅ 🚫✅ # old V3 fails on revoke + harvest
brownie test tests/test_double_withdraw_after_donation_part_1.py -s # ✅✅ 🚫✅ # old V3 fails on debtRatio == 0 + harvest
brownie test tests/test_double_withdraw_after_donation_part_2.py -s # ✅✅ ✅✅
brownie test tests/test_double_withdraw_after_donation_part_3.py -s # ✅✅ 🚫✅ # old V3 fails on debtRatio == 0 + harvest
brownie test tests/test_migration.py -s # ✅✅ 🚫✅ # old V3 fails on debtRatio == 0 + harvest
brownie test tests/test_misc.py -s # ✅✅ 🚫✅ # old V3 fails on revoke + harvest
brownie test tests/test_emergency_exit_part_1.py -s # ✅✅ 🚫✅ # old V3 fails on revert: no shares to redeem
brownie test tests/test_emergency_exit_part_2.py -s # ✅✅ 🚫✅ # old V3 fails on emergency shutdown + harvest
brownie test tests/test_odds_and_ends_part_1.py -s # ✅✅ ✅✅
brownie test tests/test_odds_and_ends_part_2.py -s # ✅✅ 🚫✅ # old v3 fails on revert: cannot mint zero
brownie test tests/test_simple_harvest.py -s # ✅✅ ✅🚫 # old V2 fails on harvest eventually (1 wei issue in adjustPosition)
brownie test tests/test_triggers.py -s # ✅✅ 🚫✅ # old V3 fails on debtRatio == 0 + harvest
brownie test tests/test_withdraw_after_donation_part_1.py -s # ✅✅ 🚫✅ # old V3 fails on debtRatio == 0 + harvest
brownie test tests/test_withdraw_after_donation_part_2.py -s # ✅✅ 🚫✅ # old v3 fails on revert: cannot mint zero
brownie test tests/test_withdraw_after_donation_part_3.py -s # ✅✅ 🚫✅ # old V3 fails on debtRatio == 0 + harvest
```

An embarrassingly stupid way to help speed the testing up with anvil & V3...feel free to combine more of them if you dare!

```
brownie test tests/test_change_debt.py && brownie test tests/test_cloning.py
brownie test tests/test_migration.py && brownie test tests/test_misc.py
brownie test tests/test_simple_harvest.py && brownie test tests/test_triggers.py
brownie test tests/test_emergency_exit_part_1.py && brownie test tests/test_emergency_exit_part_2.py
brownie test tests/test_odds_and_ends_part_1.py && brownie test tests/test_odds_and_ends_part_2.py
brownie test tests/test_double_withdraw_after_donation_part_1.py && brownie test tests/test_double_withdraw_after_donation_part_2.py && brownie test tests/test_double_withdraw_after_donation_part_3.py
brownie test tests/test_withdraw_after_donation_part_1.py && brownie test tests/test_withdraw_after_donation_part_2.py && brownie test tests/test_withdraw_after_donation_part_3.py
```
