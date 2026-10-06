## Inspiration

I've stared at a power bill and had the same thought: *what is actually costing me money?* The bill says $125. It doesn't say the air conditioner was $42 of it, that the fridge has been drawing 40% more since last Tuesday, or that running the water heater after 7 pm would have saved $8. Smart plugs can tell you, but nobody is putting a plug on every outlet in their house.

The research field of **non-intrusive load monitoring (NILM)** has known for thirty years that a single whole-home electrical signal carries enough information to tell appliances apart. I wanted to take that out of the papers and into a product a household would actually open: one sensor, every appliance, and advice priced in dollars you can check a week later. **Greener homes, one house at a time.**

## What it does

Synergy watches one whole-home electrical signal (power plus current harmonics, every 2 seconds) and turns it into something a family can act on.

- **Where the power goes.** A **convolutional neural network (CNN)** splits the whole-home signal into per-appliance usage: air conditioner, fridge, water heater, laptop, and so on. Every figure is labelled as estimated, and you can open any appliance to see how accurate the CNN is on recordings it never trained on.
- **This month's bill, by day.** Month-to-date, a forecast for the rest of the month with a high-end range, and a bar for every day. Tap a day and it opens that day's appliance rundown.
- **Looking ahead.** A LightGBM forecaster predicts each appliance's energy for the next 7 days against the weather forecast and flags days that will cost more than usual.
- **Appliance health.** The fridge is compared to its own history; two days of drawing more than usual raises an alert before the compressor dies.
- **Suggestions, priced.** Each week a deterministic simulator prices six kinds of habit change under the real DTE time-of-day tariff (24.1¢ at peak, 18.4¢ off-peak) and keeps the best three. **Gemini** writes each one as a plain sentence: *"On weekdays the thermostat cools 1 °F from 2 to 3 pm, then sits 2 °F warmer from 3 to 7 pm. Saves $4.56 a month."*
- **Take action.** A thermostat suggestion moves the (simulated) thermostat in two taps with a 24-hour undo. Precool installs a weekday schedule on the device itself that expires at the end of the week, so the app never changes a device on its own clock.
- **Did it really save?** A week later the verifier compares what the appliance actually cost against the forecast that priced the suggestion, shows the verified saving, and scores each kind of suggestion so next week's ranking favours what this household actually does.

## Inputs and outputs

**Inputs**
- One whole-home electrical signal: power plus 32 current harmonics, every 2 seconds
- Hourly weather, past and 7-day forecast (Open-Meteo)
- The utility's rate card: DTE time-of-day, peak and off-peak cents per kWh
- The home's appliance list and thermostat bounds, entered at sign-up
- Your taps: Take action, Dismiss, Undo

**Outputs**
- Per-appliance usage and cost, estimated by the CNN, labelled as such
- This month's bill to date, a forecast for the rest of it, and a day-by-day breakdown
- Days ahead that will cost more than usual, and which appliance drives them
- An alert when the fridge drifts from its own normal
- Three priced suggestions a week, written in plain English by Gemini
- A thermostat change or a precool schedule installed on the device, with undo
- A verified dollar saving a week later, and a score that re-ranks next week's suggestions

## How I built it

**The NILM CNN.** I designed and trained a seq2point convolutional neural network in PyTorch, from scratch, on the Mac's GPU. It reads a 299-sample window (about 10 minutes) of the whole-home signal, 35 inputs per sample (active power, current, power factor and 32 current harmonics), through a shared 5-layer 1-D convolutional encoder, then a watts head and an on/off head for each of 8 appliances. Training data is the Dinar et al. NILM dataset (*Sensors* 2025), split strictly by recording session so no test session leaks into training, plus synthetic days stitched from the training sessions' activations. The harmonics turned out to be the whole story for small loads: with them the CNN scores the laptop at an F1 of 0.99 on held-out sessions; with power alone, 0.64. I also built the classic combinatorial-optimisation baseline (the standard NILM benchmark since 1992) so I could show the CNN beating it. Inference runs in plain numpy from the saved weights, so a day of readings is split without loading PyTorch next to LightGBM (they fight over OpenMP on macOS).

**The forecaster.** LightGBM per appliance, with lagged energy, hour, weekday and the Open-Meteo temperature forecast as features, evaluated on a time-ordered 80/20 split and only deployed when it beats a seasonal-naive baseline.

**The pricing engine.** One rule: every dollar figure anywhere in the app is energy × the rate for that hour, computed in one place from a tariff the user can inspect. No model ever emits a dollar. Suggestions come from a fixed library of six templates (shift out of peak, thermostat setpoint, precool schedule, water heater setpoint, standby trim, fridge service), each priced by re-running the same cost function on a changed forecast. Precool searches every combination of length and depth and installs the best one for that week's weather.

**Gemini as narrator.** Gemini 2.5 Flash gets structured records only (appliance, change, saving) and returns one sentence per suggestion against a JSON schema. Every number in its output is checked word for word against the input; a sentence that invents or rounds a number is discarded and a plain fallback is shown instead. Gemini never proposes an action.

**The store.** SpacetimeDB on Maincloud with a TypeScript module: raw readings are append-only, every write is a reducer, the ledger of suggestions and their outcomes is never deleted, and device changes are logged before the command is sent.

**The back end.** FastAPI on Python 3.11: the only thing the dashboard talks to. Every dollar figure and every formatted number is computed here, plus sign-in, the thermostat flow and the daily CNN run.

**The front end.** React, TypeScript and Vite, styled after the Tesla energy app in light mode: sign-in, a typed intro, and a dashboard that formats nothing itself.

**The demo.** A simulated practice home, replayed through the real ingestion path at 2-second resolution over four July weeks, with a fridge fault injected on day 12 and a simulated household that follows whatever it accepts, so the verification loop closes on screen.

## Challenges I ran into

- **Making the CNN honest.** A random train/test split of 2-second samples reports near-perfect accuracy because adjacent samples are identical. I split by recording session, and the real numbers are humbler: the straightener (0.45 F1) and iron (0.89) are short bursts with only a handful of examples in 12 sessions.
- **The watts head regressing to zero.** My first CNN scored the rare appliances at 0.00: the on/off head worked, but the regression head had learned that "0 W" is usually right. Training it on on-samples only overshot the other way (a false "on" cost the iron's full 1,300 W). A class-balanced loss fixed both.
- **PyTorch and LightGBM crash together on macOS.** Both bundle an OpenMP runtime. I moved CNN inference to numpy and kept PyTorch for training only.
- **A thermostat schedule versus "never on a timer".** Precool needs the setpoint to change three times a day, which my own rule forbade. The resolution: a single tap installs a bounded schedule on the device, which runs it itself and drops it at the end of the week.
- **Pricing precool properly.** My first pricing assumed cooling could be stored with no loss and said $1.85 a week. Running the actual thermostat model against the week's weather said $0.09. The fix was to let precool search its own length and depth each week.

## Accomplishments that I'm proud of

- **I built and trained a CNN for NILM in 36 hours**, from the architecture to a deployed model: a shared convolutional encoder with per-appliance heads, trained on real recordings and evaluated on sessions it never saw. It beats the classic baseline on four appliances, and the power-only ablation proves the current harmonics are what the network is learning from.
- **The CNN runs in production without PyTorch.** I export the weights and run the forward pass in numpy, so a full day of 2-second readings is split on a laptop CPU and written to the store every day of the demo.
- **A closed loop:** suggestion, tap, device change, and a week later a verified dollar figure and a score that reshapes next week's ranking.
- **An architecture where no AI component can invent a number:** the CNN estimates watts, a deterministic engine prices them, and Gemini is checked word for word.
- **A dashboard a household could actually use**, with every number traceable to an appliance, an hour and a published rate card.

## What I learned

Most of the hard problems weren't modelling problems. They were trust problems: how to show a CNN's estimate without pretending it's a measurement, how to let a language model write for you without letting it make things up, and how to prove a saving instead of promising one. I also learned that evaluation discipline (session splits, held-out sessions, a baseline that has to be beaten) is what separates a demo from a product, and that a 150-line baseline is worth building before the neural network, because it tells you whether the CNN earned its place. And on the modelling side: the loss function mattered more than the architecture. Three training runs with the same CNN gave three very different appliances-that-work, and the fix each time was in how the loss weighed rare appliances, not in the layers.

## What's next for Synergy

- A real clamp sensor on a breaker panel, and a smart plug used for one week to fine-tune the CNN's heads to a specific home's appliances while the shared encoder stays frozen.
- Enter your own utility's price plan at sign-up, so every figure is priced in your rates.
- A live Nest adapter for the thermostat; the interface already has one method to swap.
- Hourly grid carbon intensity, so shifting load also shows the CO₂ it avoids at that hour.
- More appliances (dryer, oven, EV charger) from public datasets, and the CNN trained on far more homes.
