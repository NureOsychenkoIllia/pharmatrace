// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title Participant registry interface
/// @notice Read side used by the batch and incident contracts.
interface IParticipantRegistry {
    /// @notice Kind of a supply-chain participant
    enum Kind {
        None,
        Manufacturer,
        Distributor,
        Pharmacy,
        Regulator
    }

    /// @notice Registration status
    enum Status {
        None,
        Active,
        Suspended,
        Revoked
    }

    /// @notice Returns the participant record
    function participantOf(address account)
        external
        view
        returns (Kind kind, Status status, bytes32 licenseHash, bytes2 city, uint64 registeredAt);

    /// @notice Returns the participant kind
    function kindOf(address account) external view returns (Kind);

    /// @notice Whether the account is active and has the expected kind
    function isActive(address account, Kind kind) external view returns (bool);

    /// @notice Whether the account is active regardless of kind
    function isActiveParticipant(address account) external view returns (bool);
}
