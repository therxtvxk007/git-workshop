import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { SessionProvider } from "./components/SessionProvider";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Nothing here is retried. See src/lib/queries.ts: every failure mode the
      // adapters raise is one a retry cannot fix.
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("#root is missing from index.html");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      {/*
        `v7_relativeSplatPath` is inert for these routes and opting in early
        keeps the next major from arriving as a surprise.

        `v7_startTransition` is deliberately NOT enabled. It wraps router state
        updates in a React transition, which defers them below the click that
        caused them -- and since every filter control here is a controlled input
        driven by the URL, the checkbox the analyst just clicked stays visually
        unchecked until the transition lands. Filter controls have to answer the
        click immediately.
      */}
      <BrowserRouter future={{ v7_relativeSplatPath: true }}>
        <SessionProvider>
          <App />
        </SessionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
