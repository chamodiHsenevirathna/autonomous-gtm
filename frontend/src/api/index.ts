import type { Api } from './client';
import { createHttpApi } from './http';
import { createMockApi } from './mock/mockApi';

export function createApi(): Api {
  const mode = import.meta.env.VITE_API_MODE ?? 'mock';
  return mode === 'http' ? createHttpApi() : createMockApi();
}
export * from './client';
export * from './types';
