## Template A: Drill start
[DR DRILL] Drill {drill_id} ({scenario}) has started. This is a simulation; no production systems are affected.

## Template B: Step in progress
[DR DRILL] {drill_id}: {step} is awaiting approval from the {owner}. Simulated RTO so far: {rto} s of 900 s.

## Template C: Failure or rollback
[DR DRILL] {drill_id}: {step} requires rollback approval from the {owner}. Reversing completed changes in reverse order. Simulated RTO so far: {rto} s.

## Template D: Completion
[DR DRILL] {drill_id} ({scenario}) finished: {outcome}. Simulated RTO {rto} s of 900 s. See the drill report for deviations and improvements.
