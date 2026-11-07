
### how we name branches
For now:
- БалчаНМ name branches accoriding to the Pull request name: "FirstPR,SecondPR"
- ТегеньСБ name branches accoriding if the task is document oriented he prefixes with "docs/" with specific name whereas the task is feature "feat/" with specific name.
In the future for implementation we tend to follow the trend used in git lecutre: feature/, release/, backport/, hotfix/, main/
### how we write commits

We commit according to the task we shared. If we finish the task we were assigned we commit and explain it.
### who reviews and how

**Both participate**
- БалчаНМ
- ТегеньСБ

Reviews eachother task and commit.

### Definition of Done: when a task is considered complete.


A work item is Done only when all six conditions are satisfied:

|Condition	|What it means in practice	|Evidence needed
|---|---:|--:|
|Behavior	|Required functionality and edge cases are agreed, not just the happy path.	|Agreed EARS/BDD scenarios, edge cases, error behavior, invariants.|
|Contracts	|Interfaces between modules are compatible.	|ToolResult, WeatherError, ConversionResult, API DTOs, error codes, version fields.|
|Checks	|Necessary tests pass on the final code integrated with the actual up-to-date base branch.	|Test run against merged/up-to-date base, not a stale branch.|
|Review	|Significant questions resolved; consequences reviewed by affected owners.	|Review by module owners, API owner, UI owner, data owner as needed.|
|Docs and Data	|MR description, contracts, and necessary DB migrations are in agreed state.	|Updated MR, contract docs, migration scripts, or explicit “no migration needed.”|
|Integration	|Change is accepted into main; team retains responsibility after acceptance.	|Merged to main; post-merge ownership acknowledged.|
