"use client";

import { Moon, Sun, Monitor } from "lucide-react";
import * as React from "react";

import { useAuth } from "@/components/auth/auth-context";
import { applyTheme, storeTheme } from "@/components/theme/theme-provider";
import { updatePreferences } from "@/lib/api";
import type { Theme } from "@/types";

const THEMES: { value: Theme; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { value: "dark", label: "Dark", icon: Moon },
  { value: "light", label: "Light", icon: Sun },
  { value: "system", label: "System", icon: Monitor },
];

export function ThemeToggle() {
  const { user, refresh } = useAuth();
  const [currentTheme, setCurrentTheme] = React.useState<Theme>(
    user?.preferences?.theme ?? "dark",
  );
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (user?.preferences?.theme) {
      setCurrentTheme(user.preferences.theme);
    }
  }, [user?.preferences?.theme]);

  const handleSelect = async (theme: Theme) => {
    setCurrentTheme(theme);
    applyTheme(theme);
    storeTheme(theme);

    if (user) {
      setSaving(true);
      try {
        await updatePreferences({ theme });
        await refresh();
      } catch {
        /* Local state and storage remain updated */
      } finally {
        setSaving(false);
      }
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label="Theme selector"
      className="flex items-center gap-0.5 rounded-lg border border-line bg-elevated/70 p-0.5"
    >
      {THEMES.map(({ value, label, icon: Icon }) => {
        const active = currentTheme === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={saving}
            onClick={() => handleSelect(value)}
            title={`Switch to ${label} theme`}
            className={`flex items-center justify-center rounded-md px-2 py-1 text-xs transition-all ${
              active
                ? "bg-surface font-medium text-ink shadow-sm border border-line/60"
                : "text-muted hover:text-ink hover:bg-surface/50"
            }`}
          >
            <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span className="ml-1 hidden sm:inline text-2xs">{label}</span>
          </button>
        );
      })}
    </div>
  );
}
