"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { keys } from "@/lib/query-keys";
import { interactions } from "@/services/api";
import type { EventType, FeedbackState } from "@/types/api";

const NEUTRAL: FeedbackState = { liked: false, disliked: false, saved: false };

/** Like / dislike / save state of the given tracks (one request per visible list). */
export function useFeedbackStates(trackIds: string[]) {
  const ids = [...new Set(trackIds)].sort();
  const query = useQuery({
    queryKey: keys.feedback(ids.join(",")),
    queryFn: () => interactions.state(ids),
    enabled: ids.length > 0,
    staleTime: 60_000,
  });
  return (trackId: string): FeedbackState =>
    query.data?.states[trackId] ?? NEUTRAL;
}

const EFFECT: Partial<Record<EventType, Partial<FeedbackState>>> = {
  like: { liked: true, disliked: false },
  unlike: { liked: false },
  dislike: { disliked: true, liked: false },
  undislike: { disliked: false },
  save: { saved: true },
  unsave: { saved: false },
};

/**
 * Record one feedback event. The new state shows immediately (optimistic), and recommendations
 * and taste data are refetched because the backend rebuilds the taste profile on every event.
 */
export function useFeedback() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      trackId,
      eventType,
      requestId,
    }: {
      trackId: string;
      eventType: EventType;
      requestId?: string;
    }) =>
      interactions.record([
        { track_id: trackId, event_type: eventType, request_id: requestId },
      ]),
    onMutate: async ({ trackId, eventType }) => {
      await client.cancelQueries({ queryKey: keys.feedbackAll });
      const snapshots = client.getQueriesData<{
        states: Record<string, FeedbackState>;
      }>({
        queryKey: keys.feedbackAll,
      });
      for (const [key, data] of snapshots) {
        if (!data?.states[trackId]) continue;
        client.setQueryData(key, {
          states: {
            ...data.states,
            [trackId]: { ...data.states[trackId], ...EFFECT[eventType] },
          },
        });
      }
      return { snapshots };
    },
    onError: (_error, _variables, context) => {
      for (const [key, data] of context?.snapshots ?? [])
        client.setQueryData(key, data);
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.feedbackAll });
      void client.invalidateQueries({ queryKey: keys.tasteProfile });
      void client.invalidateQueries({ queryKey: keys.taste });
      void client.invalidateQueries({ queryKey: ["history"] });
      // Recommendations reflect the feedback on their next visit, without reshuffling the page
      // the user is interacting with right now.
      for (const queryKey of [
        keys.forYouAll,
        keys.because,
        ["hidden-gems"],
        ["mood"],
      ]) {
        void client.invalidateQueries({ queryKey, refetchType: "none" });
      }
    },
  });
}

export function useHistory(eventTypes: EventType[], limit = 20) {
  return useQuery({
    queryKey: keys.history(eventTypes.join(",")),
    queryFn: () => interactions.history({ limit, eventTypes }),
  });
}
