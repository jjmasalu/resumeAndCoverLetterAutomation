"use client";

import { useRef, useSyncExternalStore, createContext, useContext, useCallback } from "react";

type Theme = "dark" | "light";

function getThemeSnapshot(): Theme {
  if (typeof window === "undefined") return "dark";
  return localStorage.getItem("theme") === "light" ? "light" : "dark";
}

function getServerSnapshot(): Theme {
  return "dark";
}

const ThemeContext = createContext<{
  theme: Theme;
  toggleTheme: () => void;
}>({
  theme: "dark",
  toggleTheme: () => {},
});

export function useTheme() {
  return useContext(ThemeContext);
}

export default function ThemeProvider({ children }: { children: React.ReactNode }) {
  const listenersRef = useRef<Set<() => void>>(new Set());

  const subscribe = useCallback((listener: () => void) => {
    listenersRef.current.add(listener);
    return () => { listenersRef.current.delete(listener); };
  }, []);

  const theme = useSyncExternalStore(subscribe, getThemeSnapshot, getServerSnapshot);

  // Apply class on mount and when theme changes
  if (typeof document !== "undefined") {
    document.documentElement.classList.toggle("light", theme === "light");
  }

  const toggleTheme = useCallback(() => {
    const next = theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", next);
    document.documentElement.classList.toggle("light", next === "light");
    listenersRef.current.forEach((l) => l());
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}
