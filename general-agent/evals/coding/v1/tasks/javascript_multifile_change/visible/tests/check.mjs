import assert from 'node:assert/strict';
import {total} from '../index.js';
assert.equal(total([10,20],0.1),27);
