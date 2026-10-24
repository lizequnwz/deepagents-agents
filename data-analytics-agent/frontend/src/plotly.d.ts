interface PlotlyAPI {
  react: (
    element: HTMLElement,
    data: unknown[],
    layout: Record<string, unknown>,
    config: Record<string, unknown>,
  ) => Promise<void>;
  relayout: (
    element: HTMLElement,
    layout: Record<string, unknown>,
  ) => Promise<void>;
  purge: (element: HTMLElement) => void;
  Plots: { resize: (element: HTMLElement) => Promise<void> | void };
}
declare module "plotly.js-dist-min" {
  const Plotly: PlotlyAPI;
  export default Plotly;
}
