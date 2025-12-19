/*
 * Copyright 2025 Daytona Platforms Inc.
 * SPDX-License-Identifier: AGPL-3.0
 */

import { ApiProperty } from '@nestjs/swagger'
import { IsBoolean, IsOptional, IsString, IsArray, IsEnum } from 'class-validator'
import { Type } from 'class-transformer'
import { SandboxState } from '../enums/sandbox-state.enum'
import { ToArray } from '../../common/decorators/to-array.decorator'
import { PageLimit } from '../../common/decorators/page-limit.decorator'

export const SANDBOX_VALID_QUERY_STATES = Object.values(SandboxState).filter(
  (state) => state !== SandboxState.DESTROYED,
)

export class ListSandboxesQueryDto {
  @ApiProperty({
    name: 'cursor',
    description: 'Pagination cursor from a previous response',
    required: false,
    type: String,
  })
  @IsOptional()
  @IsString()
  cursor?: string

  @PageLimit(100)
  limit = 100

  @ApiProperty({
    name: 'name',
    description: 'Filter by name prefix (case-sensitive). Can not be combined with "states"',
    required: false,
    type: String,
  })
  @IsOptional()
  @IsString()
  name?: string

  @ApiProperty({
    name: 'includeErroredDeleted',
    description: 'Include results with errored state and deleted desired state',
    required: false,
    type: Boolean,
    default: false,
  })
  @IsOptional()
  @Type(() => Boolean)
  @IsBoolean()
  includeErroredDeleted?: boolean

  @ApiProperty({
    name: 'states',
    description: 'List of states to filter by. Can not be combined with "name"',
    required: false,
    enum: SANDBOX_VALID_QUERY_STATES,
    isArray: true,
  })
  @IsOptional()
  @ToArray()
  @IsArray()
  @IsEnum(SANDBOX_VALID_QUERY_STATES, {
    each: true,
    message: `each value must be one of the following values: ${SANDBOX_VALID_QUERY_STATES.join(', ')}`,
  })
  states?: SandboxState[]
}
