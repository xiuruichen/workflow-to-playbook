# Pilot report

60 cases; you acted on 24 and left 36 alone.

## The rule we found

Read it as a hypothesis about your habits, not as a fact. 'changed_x' means x differs from the previous case.

- spikes <= 2.5 and hours_since_last_check <= 28 -> none (32/37)
- spikes <= 2.5 and hours_since_last_check > 28 and spikes <= 1 -> none (2/2)
- spikes <= 2.5 and hours_since_last_check > 28 and spikes > 1 -> Stop the run (3/3)
- spikes > 2.5 and changed_batch_size <= 0.5 -> Stop the run (16/16)
- spikes > 2.5 and changed_batch_size > 0.5 -> none (2/2)

It fits 92% of your 60 choices. Fitted on your first 42, it predicts 83% of your last 18 (always doing the most common thing would get 78%).

## The 14 choice(s) it cannot explain

For each: what the rule expected, what you did, and what was on screen. These are the places to explain why.

- case000: you chose none; the rule expected Stop the run. Saw: spikes = 0, batch_size = 256, loss = 2.94, hours_since_last_check = 12, dataset = new. [O4, tacit 3/4]
- case012: you chose Stop the run; the rule expected none. Saw: spikes = 2, batch_size = 4096, loss = 2.47, hours_since_last_check = 30, dataset = clean. [O3, tacit 2/4]
- case015: you chose Stop the run; the rule expected none. Saw: spikes = 2, batch_size = 4096, loss = 2.4, hours_since_last_check = 29, dataset = new. [O3, tacit 2/4]
- case016: you chose none; the rule expected Stop the run. Saw: spikes = 3, batch_size = 256, loss = 2.34, hours_since_last_check = 4, dataset = new. [O5, tacit 4/4]
- case017: you chose Stop the run; the rule expected none. Saw: spikes = 2, batch_size = 256, loss = 2.34, hours_since_last_check = 24, dataset = clean. [O3, tacit 2/4]
- case018: you chose Stop the run; the rule expected none. Saw: spikes = 2, batch_size = 256, loss = 2.34, hours_since_last_check = 24, dataset = clean. [O3, tacit 2/4]
- case022: you chose none; the rule expected Stop the run. Saw: spikes = 0, batch_size = 512, loss = 2.19, hours_since_last_check = 30, dataset = clean. [O4, tacit 3/4]
- case029: you chose Stop the run; the rule expected none. Saw: spikes = 2, batch_size = 512, loss = 1.82, hours_since_last_check = 5, dataset = clean. [O3, tacit 2/4]
- case032: you chose Stop the run; the rule expected none. Saw: spikes = 2, batch_size = 512, loss = 1.59, hours_since_last_check = 18, dataset = clean. [O3, tacit 2/4]
- case034: you chose Stop the run; the rule expected none. Saw: spikes = 2, batch_size = 512, loss = 1.55, hours_since_last_check = 29, dataset = new. [O3, tacit 2/4]
- case037: you chose none; the rule expected Stop the run. Saw: spikes = 0, batch_size = 512, loss = 1.52, hours_since_last_check = 29, dataset = clean. [O4, tacit 3/4]
- case038: you chose Stop the run; the rule expected none. Saw: spikes = 2, batch_size = 512, loss = 1.45, hours_since_last_check = 12, dataset = clean. [O3, tacit 2/4]
- case039: you chose none; the rule expected Stop the run. Saw: spikes = 3, batch_size = 1024, loss = 1.39, hours_since_last_check = 18, dataset = new. [O5, tacit 4/4]
- case048: you chose none; the rule expected Stop the run. Saw: spikes = 1, batch_size = 256, loss = 1.09, hours_since_last_check = 22, dataset = clean. [O4, tacit 3/4]

## Your own words against the fitted rule

You wrote: "Mostly: two or more spikes means I stop the run, unless I just changed the batch size, then I wait. I am a bit more patient when the dataset is new."

- The fit uses `changed_batch_size`: you mention it.
- The fit uses `hours_since_last_check`: **you did not mention it.**
- The fit uses `spikes`: you mention it.
- You mention `dataset`, but the fit does not use it.

Judge for yourself: is the fitted rule partly right? What would you correct?

## Next

Answer the questions about the unexplained choices (`python -m playbook pilot elicit pilot_log.json`), which refits the rule with what you tell it. Then judge: is the new rule closer to how you decide?
