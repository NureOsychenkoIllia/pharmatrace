// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title Batch token interface
/// @notice Narrow interface used by the incident registry to recall a batch.
interface IBatchToken {
    /// @notice Recalls a batch on behalf of the regulator
    /// @param tokenId Batch identifier
    /// @param reasonHash Hash of the recall reason document
    function recallByIncident(uint256 tokenId, bytes32 reasonHash) external;

    /// @notice Returns the batch state as its numeric enum value
    function batchState(uint256 tokenId) external view returns (uint8);
}
