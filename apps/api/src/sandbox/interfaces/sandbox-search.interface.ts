/*
 * Copyright 2025 Daytona Platforms Inc.
 * SPDX-License-Identifier: AGPL-3.0
 */

import { Sandbox } from '../entities/sandbox.entity'
import { SandboxState } from '../enums/sandbox-state.enum'
import { SandboxSearchSortField, SandboxSearchSortDirection } from '../dto/search-sandboxes-query.dto'

export interface SandboxSearchFilters {
  id?: string
  name?: string
  labels?: { [key: string]: string }
  includeErroredDeleted?: boolean
  states?: SandboxState[]
  snapshots?: string[]
  regionIds?: string[]
  minCpu?: number
  maxCpu?: number
  minMemoryGiB?: number
  maxMemoryGiB?: number
  minDiskGiB?: number
  maxDiskGiB?: number
  isPublic?: boolean
  isRecoverable?: boolean
  createdAtAfter?: Date
  createdAtBefore?: Date
  lastEventAfter?: Date
  lastEventBefore?: Date
  sort?: SandboxSearchSortField
  order?: SandboxSearchSortDirection
}

export interface SandboxSearchResult {
  items: Sandbox[]
  nextCursor: string | null
}

/**
 * Interface for sandbox search operations
 * Provides search functionality for sandboxes with filtering and cursor-based pagination
 */
export interface SandboxSearchAdapter {
  /**
   * Search sandboxes for an organization
   * @param organizationId - Organization ID to filter by
   * @param cursor - Cursor for pagination (from previous response)
   * @param limit - Maximum number of results to return
   * @param filters - Optional filters to apply
   * @returns Paginated search results with cursor for next page
   */
  search(
    organizationId: string,
    cursor: string | undefined,
    limit: number,
    filters?: SandboxSearchFilters,
  ): Promise<SandboxSearchResult>
}
