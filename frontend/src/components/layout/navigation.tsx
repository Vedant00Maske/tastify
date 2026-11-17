"use client";

import {
  Compass,
  Home,
  LibraryBig,
  LogOut,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  Waves,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useState, type ComponentType, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/primitives";
import { useLogout, useMe } from "@/features/auth/queries";
import { usePlaylists } from "@/features/playlists/queries";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
}

export const MAIN_NAV: NavItem[] = [
  { href: "/home", label: "Home", icon: Home },
  { href: "/discover", label: "Discover", icon: Compass },
  { href: "/moods", label: "Mood Mix", icon: Waves },
  { href: "/search", label: "Search", icon: Search },
];

export const LIBRARY_NAV: NavItem[] = [
  { href: "/playlists", label: "Playlists", icon: LibraryBig },
  { href: "/taste", label: "Your taste", icon: Sparkles },
];

/** `href="/"` on signed-out pages: "/" is resolved by the proxy, and nothing signed-in is prefetched. */
export function BrandLogo({
  className,
  href = "/home",
}: {
  className?: string;
  href?: string;
}) {
  return (
    <Link
      href={href}
      prefetch={href === "/" ? false : undefined}
      aria-label="TASTIFY home"
      className={cn(
        "inline-flex items-center gap-2 font-display text-xl font-extrabold tracking-tight",
        className,
      )}
    >
      <span className="grid size-7 place-items-center rounded-button-sm bg-accent text-on-accent">
        <Waves className="size-4" />
      </span>
      TASTIFY
    </Link>
  );
}

function isActive(pathname: string | null, href: string) {
  return (
    pathname !== null && (pathname === href || pathname.startsWith(`${href}/`))
  );
}

function NavLink({
  item,
  pathname,
}: {
  item: NavItem;
  pathname: string | null;
}) {
  const active = isActive(pathname, item.href);
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-button px-3 py-2.5 text-sm font-semibold transition-colors duration-150",
        active
          ? "bg-surface text-fg"
          : "text-fg-secondary hover:bg-surface/60 hover:text-fg",
      )}
    >
      <item.icon className={cn("size-5", active && "text-accent")} />
      {item.label}
    </Link>
  );
}

/**
 * The pathname is runtime data: it is read inside a Suspense boundary (see `withPathname`), and
 * the prerendered shell shows the same navigation without an active item.
 */
function withPathname(
  Component: (props: { pathname: string | null }) => ReactNode,
) {
  function Active() {
    return <Component pathname={usePathname()} />;
  }
  return function WithPathname() {
    return (
      <Suspense fallback={<Component pathname={null} />}>
        <Active />
      </Suspense>
    );
  };
}

function Sidebar({ pathname }: { pathname: string | null }) {
  const playlists = usePlaylists();
  return (
    <aside className="hidden w-64 shrink-0 flex-col gap-6 border-r border-border bg-background-secondary px-4 py-6 lg:flex">
      <BrandLogo className="px-2" />
      <nav aria-label="Main" className="flex flex-col gap-1">
        {MAIN_NAV.map((item) => (
          <NavLink key={item.href} item={item} pathname={pathname} />
        ))}
      </nav>
      <nav aria-label="Library" className="flex min-h-0 flex-1 flex-col gap-1">
        <p className="px-3 pb-1 text-meta font-semibold tracking-wider text-fg-muted uppercase">
          Library
        </p>
        {LIBRARY_NAV.map((item) => (
          <NavLink key={item.href} item={item} pathname={pathname} />
        ))}
        <div className="mt-2 flex min-h-0 flex-col gap-0.5 overflow-y-auto">
          {playlists.data?.playlists.slice(0, 20).map((playlist) => (
            <Link
              key={playlist.id}
              href={`/playlists/${playlist.id}`}
              aria-current={
                pathname === `/playlists/${playlist.id}` ? "page" : undefined
              }
              className="truncate rounded-button-sm px-3 py-1.5 text-support text-fg-secondary hover:bg-surface/60 hover:text-fg aria-[current=page]:text-fg"
            >
              {playlist.name}
            </Link>
          ))}
        </div>
      </nav>
      <NavLink
        item={{ href: "/settings", label: "Settings", icon: Settings }}
        pathname={pathname}
      />
    </aside>
  );
}

function MobileTabs({ pathname }: { pathname: string | null }) {
  const items = [
    MAIN_NAV[0],
    MAIN_NAV[1],
    MAIN_NAV[3],
    LIBRARY_NAV[0],
    LIBRARY_NAV[1],
  ];
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-border bg-background-secondary/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
    >
      {items.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold",
              active ? "text-accent" : "text-fg-secondary",
            )}
          >
            <item.icon className="size-5" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function SearchBar({ className }: { className?: string }) {
  const router = useRouter();
  const [value, setValue] = useState("");
  return (
    <form
      role="search"
      className={cn("relative w-full max-w-md", className)}
      onSubmit={(event) => {
        event.preventDefault();
        router.push(`/search?q=${encodeURIComponent(value.trim())}`);
      }}
    >
      <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-fg-muted" />
      <label htmlFor="global-search" className="sr-only">
        Search tracks and artists
      </label>
      <input
        id="global-search"
        type="search"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Search tracks and artists"
        className="h-10 w-full rounded-full border border-border bg-surface pr-4 pl-10 text-sm text-fg placeholder:text-fg-muted focus:border-accent focus:outline-none"
      />
    </form>
  );
}

export function ProfileMenu() {
  const me = useMe();
  const logout = useLogout();
  const name = me.data?.display_name || me.data?.email.split("@")[0] || "You";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="secondary" size="icon" aria-label="Account menu">
          <span className="font-display text-sm font-bold uppercase">
            {name.slice(0, 1)}
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>{me.data?.email ?? "Signed in"}</DropdownMenuLabel>
        <DropdownMenuItem asChild>
          <Link href="/taste">
            <UserRound /> Your taste
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/settings#preferences">
            <SlidersHorizontal /> Music preferences
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/settings">
            <Settings /> Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => logout.mutate()}>
          <LogOut /> Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppHeader() {
  return (
    <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-border/60 bg-background/85 px-4 py-3 backdrop-blur sm:px-6 lg:px-10">
      <BrandLogo className="lg:hidden" />
      <SearchBar className="hidden sm:block" />
      <div className="ml-auto flex items-center gap-2">
        <Button
          asChild
          variant="ghost"
          size="icon"
          className="sm:hidden"
          aria-label="Search"
        >
          <Link href="/search">
            <Search />
          </Link>
        </Button>
        <ProfileMenu />
      </div>
    </header>
  );
}

export const AppSidebar = withPathname(Sidebar);
export const MobileNavigation = withPathname(MobileTabs);
