# Required PR checks

Policy inspected on 2026-10-06. The active public
[Milestone 6 quality gates ruleset](https://github.com/ShinningF1eld/RestaurantOS/rules/24579144)
targets the default branch (`main`) and requires a pull request plus the actual
GitHub Actions check `Milestone 6 acceptance` (integration ID 15368).
Branches must be up to date. Force pushes and deletion are blocked.

The required check aggregates all ten matrix gates in `.github/workflows/ci.yml`.
It runs with `always()` and returns failure if any gate fails, is cancelled, or
does not succeed. There are no event path filters. `push`, `pull_request`, and
`merge_group` emit the same aggregate name; a merge queue is not currently enabled.
Do not rename the check without updating and re-verifying the rule.

No actor has a merge bypass. Zero approving reviews are required for this
individual-owner workflow; automated acceptance is still mandatory. The owner
can administratively edit repository rules, so governance requires keeping the
ruleset active, checking its changes, and repeating the disposable PR proof after
policy/workflow changes. Administrator access does not bypass the ordinary merge
button under the inspected policy.

The dated [Milestone 6 verification](../milestone6/milestone-6-verification.md) records
missing/pending, failing and passing states of
[disposable PR #16](https://github.com/ShinningF1eld/RestaurantOS/pull/16).
The temporary failing regression is removed by a subsequent commit, and the
probe PR is closed without merging. Implementation remains in PR #15.
Historical captures and the actual API ruleset record are in [evidence](evidence/).
