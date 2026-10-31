/** Bounded operations for decision tools. No expression strings or executable source. */
export function calculate(operation: string, values: number[], weights: number[] = [], budget?: number): number {
  if (!values.length || values.length > 20 || values.some(v => !Number.isFinite(v) || Math.abs(v) > 1e15)) throw new Error('Enter finite values within the supported range.');
  let result: number;
  switch (operation) {
    case 'sum': case 'budget': result = values.reduce((a, b) => a + b, 0); if (operation === 'budget' && budget !== undefined) result = budget - result; break;
    case 'subtract': result = values.slice(1).reduce((a, b) => a - b, values[0]); break;
    case 'multiply': result = values.reduce((a, b) => a * b, 1); break;
    case 'divide': if (values.slice(1).includes(0)) throw new Error('Cannot divide by zero.'); result = values.slice(1).reduce((a, b) => a / b, values[0]); break;
    case 'weighted_average': { const w = values.map((_, i) => weights[i] ?? 1); const sum = w.reduce((a, b) => a + b, 0); if (!sum || w.some(v => v < 0 || !Number.isFinite(v))) throw new Error('Weights must be nonnegative and total more than zero.'); result = values.reduce((a, v, i) => a + v * w[i], 0) / sum; break; }
    case 'compound': if (values.length !== 3 || values[2] < 0 || values[2] > 1000) throw new Error('Compound requires principal, rate and 0–1000 periods.'); result = values[0] * (1 + values[1] / 100) ** values[2]; break;
    case 'compare': result = Math.max(...values); break;
    case 'filter': result = values.filter(v => v >= (budget ?? 0)).length; break;
    case 'rule': result = values.every(v => v >= (budget ?? 0)) ? 1 : 0; break;
    default: throw new Error('Unsupported operation.');
  }
  if (!Number.isFinite(result) || Math.abs(result) > 1e15) throw new Error('Result exceeds the supported range.');
  return result;
}
export function haversine(a: {lat: number; lon: number}, b: {lat: number; lon: number}): number {
  const rad = Math.PI / 180, dlat = (b.lat - a.lat) * rad, dlon = (b.lon - a.lon) * rad;
  const h = Math.sin(dlat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dlon / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(Math.min(1, h)));
}
