# Solar Savings

A Home Assistant integration that shows how much money your solar panels saved you.

It counts the solar energy your home used itself (including energy that went into a home battery) and multiplies it by a price. Energy exported to the grid is never counted as savings, because you are already paid for it separately.

## What you get

- **Solar self-consumed energy** (kWh, `total_increasing`): solar energy kept at home.
- **Solar savings** (your Home Assistant currency, `total`): what that energy would have cost from the grid.
- With more than one solar sensor, the same two sensors for each source as well.

## How it counts

For every UTC hour:

```text
kept    = max(0, produced − exported)
savings = kept × price
```

- Production and export are read from cumulative energy sensors (kWh or Wh).
- With several solar sensors, the hour's export is split by production share.
- Without an export sensor, everything produced counts as kept.
- Solar that charges a battery counts in the hour it was produced. Discharging the battery later is not counted again. Grid energy that charges the battery is not production, so it never counts.
- The price is either a fixed number or a price entity. With an entity, each bit of energy is priced at the moment it is measured, so a dynamic tariff works hour by hour. Units ending in `/MWh` or `/Wh` are converted to per kWh.

The hour is locked when it ends. While an hour is open, the sensors keep their committed value and show the live estimate in the `provisional_kwh` and `provisional_savings` attributes. This is why the totals never go down, even if export for the hour is reported after production.

Meter resets (a drop to near zero) count only the growth after the reset. A small drop is treated as a glitch and ignored. Unavailable and unknown states are skipped. Totals are saved and survive restarts.

## Install with HACS

1. In Home Assistant, open **HACS**.
2. Click the three dots in the top right, then **Custom repositories**.
3. Repository: `https://github.com/TUNER88/ha-solar-savings`, Type: **Integration**. Click **Add**.
4. Search for **Solar Savings** in HACS, open it and click **Download**.
5. Restart Home Assistant.

## Configure

1. **Settings → Devices & services → Add integration → Solar Savings**.
2. Pick a name, one or more solar production sensors, and optionally your grid export sensor. These are the same cumulative sensors you use in the Energy dashboard.
3. Choose **Fixed price** and enter what you pay per kWh from the grid, or **Price from an entity** and pick your price sensor.

You can change sensors and price later with **Configure** on the integration. Totals so far are kept.

## Show it on a dashboard

The built-in Energy dashboard cannot show this. Its Cost column only comes from Home Assistant core, and custom integrations cannot add to it. Use normal cards instead.

Savings this month (statistic card):

```yaml
type: statistic
entity: sensor.solar_savings_solar_savings
name: Solar savings this month
period:
  calendar:
    period: month
stat_type: change
```

Both totals at a glance:

```yaml
type: entities
title: Solar
entities:
  - entity: sensor.solar_savings_solar_savings
  - entity: sensor.solar_savings_solar_self_consumed_energy
```

Daily savings for the last 30 days:

```yaml
type: statistics-graph
entities:
  - sensor.solar_savings_solar_savings
stat_types:
  - change
period: day
days_to_show: 30
chart_type: bar
```

The entity IDs depend on the name you chose. Check them under the integration's device.

## Known limits

- Hourly buckets in UTC. Energy reported shortly after the hour boundary counts in the new hour.
- Nothing before setup is counted. There is no backfill from history.
- Battery round-trip losses are not modeled. Solar that charged the battery counts in full.
- Battery energy stored in one hour and exported in a later hour is not taken back.
- A price entity in cents (for example `ct/kWh`) is not converted. Use a template sensor in your currency per kWh.

## License

MIT
