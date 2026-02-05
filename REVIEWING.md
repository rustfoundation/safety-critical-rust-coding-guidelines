# Reviewing coding guidelines

This document is for members reviewing coding guideline issues and PRs (Producers).
If you are contributing a guideline, start with [CONTRIBUTING.md](CONTRIBUTING.md).

## Reviewer Bot Commands

> [!NOTE]
> These commands only apply in the context of coding guideline issues.

Before we continue, here's a preamble on how the reviewer bot helps reviewers do their job.

1. The reviewer bot (`guidelines-bot`) automatically assigns reviewers to coding guideline issues and PRs using a round-robin system.

2. Only members marked as "Producer" in the consortium's [`members.md`](https://github.com/rustfoundation/safety-critical-rust-consortium/blob/main/subcommittee/coding-guidelines/members.md) are included in the rotation.

3. The queue's state is stored in [Issue #314](https://github.com/rustfoundation/safety-critical-rust-coding-guidelines/issues/314).

4. All commands are invoked by mentioning `@guidelines-bot` in a comment.

Round-robin here means the bot maintains a queue of Producers and a `current_index` cursor. Each assignment takes the next eligible reviewer in queue order and advances the cursor; the queue order does not change, except when `/pass` repositions the reviewer to be next up for future assignments. If no eligible reviewer is available (queue empty or all candidates skipped), the bot leaves the issue or PR unassigned and posts: "No reviewers available in the queue. Please use `@guidelines-bot /sync-members` to update the queue."

Down below are the available commands.

### Pass this Review to the next Producer

```
@guidelines-bot /pass [optional reason]
```

Use this when you cannot review a specific issue/PR but want to remain in the rotation for future assignments. The next reviewer in the queue will be assigned instead.

**Example:**
```
@guidelines-bot /pass Not familiar enough with FFI to review this one
```

### Step Away from Queue

```
@guidelines-bot /away YYYY-MM-DD [optional reason]
```

Use this to temporarily remove yourself from the reviewer queue until the specified date. You'll be automatically added back when the date arrives. If you're currently assigned to an issue/PR, the next reviewer will be assigned.

**Example:**
```
@guidelines-bot /away 2025-02-15 On vacation
```

### Claim a Review

```
@guidelines-bot /claim
```

Use this to assign yourself as the reviewer for an issue/PR. This removes any existing reviewer assignment. Only Producers can claim reviews.

**Example:**
```
@guidelines-bot /claim
```

### Release Your Assignment

```
@guidelines-bot /release [reason]
```

Use this to release your assignment from an issue/PR without automatically assigning someone else. The issue/PR will be left unassigned. Use `/pass` if you want to automatically assign the next reviewer.

**Example:**
```
@guidelines-bot /release Need to focus on other priorities
```

### Assign a Specific Reviewer

```
@guidelines-bot /r? @username
```

Use this to assign a specific person as the reviewer. This is useful when you know someone has specific expertise relevant to the guideline.

**Example:**
```
@guidelines-bot /r? @expert-reviewer
```

### Request Next Reviewer from Queue

```
@guidelines-bot /r? producers
```

Use this to request the next reviewer from the round-robin queue for an already-open issue or PR. This is useful when:
- An issue/PR was opened without the `coding guideline` label and later labeled
- The original reviewer was removed and you need a new one
- You want to explicitly trigger the round-robin assignment

**Example:**
```
@guidelines-bot /r? producers
```

### Manage Labels

```
@guidelines-bot /label +label-name    # Add a label
@guidelines-bot /label -label-name    # Remove a label
```

**Example:**
```
@guidelines-bot /label +needs-discussion
@guidelines-bot /label -ready-for-review
```

### Sync Members

```
@guidelines-bot /sync-members
```

Manually trigger a sync of the reviewer queue with `members.md`. This happens automatically on each workflow run, but you can force it if needed.

### Check Queue Status

```
@guidelines-bot /queue
```

Shows the current queue position, who's next up for review, and who is currently away.

### Show Available Commands

```
@guidelines-bot /commands
```

Shows all available bot commands with descriptions.

## Review Deadlines

Reviewers have **14 days** to provide initial feedback on assigned issues or PRs. This timeline helps ensure contributors receive timely responses.

Review comments or changes requested by the assigned reviewer reset the 14-day timer. When the assigned reviewer approves the PR, the review is marked complete and reminders stop.

#### What Happens If the Deadline Passes

1. **First 14 days**: The assigned reviewer should provide feedback or take action
2. **After 14 days with no activity**: The bot posts a reminder and the reviewer enters a **14-day transition period** to Observer status
3. **After 28 days total**: If still no activity, the reviewer may be transitioned from Producer to Observer status, and the review is reassigned

#### Acceptable Responses

Life happens! Any of these actions will reset the 14-day clock:

- **Post a review comment** - Any substantive feedback counts
- **Use `/pass [reason]`** - Pass the review to the next person if you can't review it
- **Use `/away YYYY-MM-DD [reason]`** - Step away temporarily (e.g., "On vacation until 2025-02-15")

#### Before You Pass: Consider the Learning Opportunity

Being assigned a review outside your comfort zone can feel daunting, but it's also one of the most effective ways to deepen your Rust knowledge. When you have a concrete goal, understanding this guideline about this feature, learning becomes focused and sticky in a way that abstract study rarely achieves.

Before reaching for `/pass`, we encourage you to spend about an hour engaging with the unfamiliar material:

- Skim the relevant FLS section and any linked documentation
- Read through the guideline with fresh eyes, noting what *does* make sense
- Search for a blog post or example that illuminates the concept
- Try compiling and tweaking the code examples yourself

You may find that an hour of targeted exploration is enough to provide meaningful feedback, even if you're not an expert. Catching unclear explanations, spotting typos, or asking "what does this term mean?" are contributions that matter because you're approaching the material without deep familiarity.

That said, `/pass` exists for good reason. If after an honest effort the material remains opaque, or if the guideline requires genuine expertise you don't have (and can't reasonably acquire in an hour), passing to someone better suited is the right call. The goal is thoughtful engagement, not struggling through a review you can't meaningfully contribute to.

#### Examples of Valid Reasons to Pass

- "Not familiar enough with FFI to review this one"
- "On holiday, please assign to someone else"
- "Swamped with other work this week"

The goal is communication, not perfection. If you need to pass or step away, just let us know!

### Queue Status

The queue's state is stored in [Issue #314](https://github.com/rustfoundation/safety-critical-rust-coding-guidelines/issues/314) and includes:

- **Current queue position** - Who will be assigned next
- **Active producers** - All reviewers in the rotation
- **Pass-until list** - Who is temporarily away and when they return
- **Recent assignments** - History of the last 20 assignments
