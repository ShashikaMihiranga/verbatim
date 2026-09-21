// Illustrative example data for the home page (the electric-vehicle sample survey). No record counts.
export type Theme = {
  name: string
  pct: number
  color: string
  subs: { name: string; pct: number }[]
  tone: [neg: number, neu: number, pos: number]
}

export const THEMES: Theme[] = [
  { name: 'Cost', pct: 30, color: 'var(--t1)', tone: [38, 40, 22], subs: [{ name: 'Upfront price', pct: 15 }, { name: 'Battery replacement cost', pct: 7.5 }, { name: 'Insurance and running costs', pct: 7.5 }] },
  { name: 'Charging', pct: 26, color: 'var(--t2)', tone: [52, 33, 15], subs: [{ name: 'No home charger', pct: 11.7 }, { name: 'Too few public chargers', pct: 9.1 }, { name: 'Slow to charge', pct: 5.2 }] },
  { name: 'Range and battery', pct: 16, color: 'var(--t3)', tone: [44, 38, 18], subs: [{ name: 'Range anxiety', pct: 9.6 }, { name: 'Battery life', pct: 6.4 }] },
  { name: 'Not needed', pct: 10, color: 'var(--t4)', tone: [30, 45, 25], subs: [{ name: 'Current car is fine', pct: 5.5 }, { name: 'Barely drive', pct: 2.5 }, { name: 'Hybrid or petrol is enough', pct: 2 }] },
  { name: 'Doubts about the technology', pct: 8, color: 'var(--t5)', tone: [47, 36, 17], subs: [{ name: 'Too new', pct: 4 }, { name: 'Resale value', pct: 4 }] },
  { name: 'Availability', pct: 5, color: 'var(--t6)', tone: [28, 40, 32], subs: [{ name: 'Waiting lists', pct: 3 }, { name: 'No dealers nearby', pct: 2 }] },
  { name: 'Uncertainty', pct: 3, color: 'var(--t7)', tone: [25, 45, 30], subs: [] },
  { name: 'Other', pct: 2, color: 'var(--other)', tone: [30, 40, 30], subs: [] },
]

// Each quote belongs to one theme (index into THEMES).
export const QUOTES: { text: string; theme: number }[] = [
  { text: 'The upfront price is just too high', theme: 0 },
  { text: 'No driveway, so I can’t install a home charger', theme: 1 },
  { text: 'I’d run out of range on my weekend trips', theme: 2 },
  { text: 'Worried about what a new battery costs', theme: 0 },
  { text: 'Not enough public chargers near me', theme: 1 },
  { text: 'My current car is fine', theme: 3 },
  { text: 'It feels too new. What will it be worth later?', theme: 4 },
  { text: 'There is a long waiting list at my dealer', theme: 5 },
]

export const AGE_GROUPS = ['18 to 29', '30 to 44', '45 to 64', '65 and over']
export const HEAT: { theme: string; values: number[] }[] = [
  { theme: 'Cost', values: [34, 33, 28, 22] },
  { theme: 'Charging', values: [22, 27, 29, 24] },
  { theme: 'Range and battery', values: [12, 15, 18, 20] },
  { theme: 'Not needed', values: [7, 8, 12, 21] },
]

export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export const TREND = {
  charging: [31, 30, 30, 29, 28, 27, 26, 25, 24, 23, 23, 22],
  cost: [28, 28, 29, 29, 30, 30, 31, 31, 32, 32, 33, 33],
}
