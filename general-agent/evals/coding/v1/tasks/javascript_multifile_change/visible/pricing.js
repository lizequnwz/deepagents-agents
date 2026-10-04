export function total(prices, discount) {
  return prices.reduce((a, b) => a + b, 0) - discount;
}
