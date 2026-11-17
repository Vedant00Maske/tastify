"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { hardNavigate } from "@/lib/navigation";
import { keys } from "@/lib/query-keys";
import { account, auth } from "@/services/api";
import type { Me } from "@/types/api";

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: account.me,
    staleTime: 5 * 60_000,
  });
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: auth.login,
    onSuccess: (me: Me) => {
      client.clear();
      client.setQueryData(keys.me, me);
    },
  });
}

export function useRegister() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: auth.register,
    onSuccess: (me: Me) => {
      client.clear();
      client.setQueryData(keys.me, me);
    },
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: auth.logout,
    onSettled: () => {
      client.clear();
      hardNavigate("/login");
    },
  });
}

export function useUpdateAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: account.update,
    onSuccess: (me: Me) => client.setQueryData(keys.me, me),
  });
}
