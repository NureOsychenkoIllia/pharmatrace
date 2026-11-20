// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";

import {IParticipantRegistry} from "./interfaces/IParticipantRegistry.sol";

/// @title Licensed supply-chain participants
/// @notice Stores manufacturer, distributor, pharmacy and regulator licenses.
/// @dev Only hashes and city codes are stored; personal data stays off-chain.
contract ParticipantRegistry is AccessControl, Pausable, IParticipantRegistry {
    bytes32 public constant VERIFIER_ROLE = keccak256("VERIFIER_ROLE");
    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");

    struct Participant {
        Kind kind;
        Status status;
        bytes32 licenseHash;
        bytes2 city;
        uint64 registeredAt;
    }

    mapping(address => Participant) private _participants;
    address[] private _accounts;
    mapping(address => bool) private _known;

    event ParticipantRegistered(
        address indexed account, Kind kind, bytes32 licenseHash, bytes2 city
    );
    event LicenseUpdated(address indexed account, bytes32 oldHash, bytes32 newHash);
    event ParticipantSuspended(address indexed account);
    event ParticipantReinstated(address indexed account);
    event ParticipantRevoked(address indexed account, bytes32 reasonHash);

    error ZeroAddress();
    error InvalidKind();
    error EmptyLicense();
    error AlreadyRegistered(address account);
    error NotRegistered(address account);
    error WrongStatus(address account, Status status);
    error InvalidCity();

    /// @param admin Receives the admin and pauser roles
    /// @param verifier Receives the verifier role
    constructor(address admin, address verifier) {
        if (admin == address(0) || verifier == address(0)) revert ZeroAddress();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(PAUSER_ROLE, admin);
        _grantRole(VERIFIER_ROLE, verifier);
    }

    /// @notice Registers a licensed participant
    /// @param account Participant address
    /// @param kind Manufacturer, distributor, pharmacy or regulator
    /// @param licenseHash Hash of the license document
    /// @param city Two-letter city or region code
    function register(address account, Kind kind, bytes32 licenseHash, bytes2 city)
        external
        onlyRole(VERIFIER_ROLE)
        whenNotPaused
    {
        if (account == address(0)) revert ZeroAddress();
        if (kind == Kind.None) revert InvalidKind();
        if (licenseHash == bytes32(0)) revert EmptyLicense();
        if (city == bytes2(0)) revert InvalidCity();
        if (_known[account]) revert AlreadyRegistered(account);

        _known[account] = true;
        _accounts.push(account);
        _participants[account] = Participant({
            kind: kind,
            status: Status.Active,
            licenseHash: licenseHash,
            city: city,
            registeredAt: uint64(block.timestamp)
        });
        emit ParticipantRegistered(account, kind, licenseHash, city);
    }

    /// @notice Replaces the license hash of an active participant
    /// @param account Participant address
    /// @param newHash New license hash
    function updateLicense(address account, bytes32 newHash)
        external
        onlyRole(VERIFIER_ROLE)
        whenNotPaused
    {
        Participant storage participant = _active(account);
        if (newHash == bytes32(0)) revert EmptyLicense();
        bytes32 oldHash = participant.licenseHash;
        participant.licenseHash = newHash;
        emit LicenseUpdated(account, oldHash, newHash);
    }

    /// @notice Suspends a participant until reinstated
    /// @param account Participant address
    function suspend(address account) external onlyRole(VERIFIER_ROLE) whenNotPaused {
        Participant storage participant = _active(account);
        participant.status = Status.Suspended;
        emit ParticipantSuspended(account);
    }

    /// @notice Reinstates a suspended participant
    /// @param account Participant address
    function reinstate(address account) external onlyRole(VERIFIER_ROLE) whenNotPaused {
        Participant storage participant = _participants[account];
        if (!_known[account]) revert NotRegistered(account);
        if (participant.status != Status.Suspended) {
            revert WrongStatus(account, participant.status);
        }
        participant.status = Status.Active;
        emit ParticipantReinstated(account);
    }

    /// @notice Revokes a license permanently
    /// @param account Participant address
    /// @param reasonHash Hash of the revocation document
    function revoke(address account, bytes32 reasonHash)
        external
        onlyRole(VERIFIER_ROLE)
        whenNotPaused
    {
        Participant storage participant = _participants[account];
        if (!_known[account]) revert NotRegistered(account);
        if (participant.status == Status.Revoked) revert WrongStatus(account, Status.Revoked);
        participant.status = Status.Revoked;
        emit ParticipantRevoked(account, reasonHash);
    }

    /// @notice Stops registrations and license changes
    function pause() external onlyRole(PAUSER_ROLE) {
        _pause();
    }

    /// @notice Resumes registrations and license changes
    function unpause() external onlyRole(PAUSER_ROLE) {
        _unpause();
    }

    /// @notice Returns the full participant record
    function participantOf(address account)
        external
        view
        returns (Kind kind, Status status, bytes32 licenseHash, bytes2 city, uint64 registeredAt)
    {
        Participant storage participant = _participants[account];
        return (
            participant.kind,
            participant.status,
            participant.licenseHash,
            participant.city,
            participant.registeredAt
        );
    }

    /// @notice Returns the participant kind
    function kindOf(address account) external view returns (Kind) {
        return _participants[account].kind;
    }

    /// @notice Whether the account is active and has the expected kind
    function isActive(address account, Kind kind) public view returns (bool) {
        Participant storage participant = _participants[account];
        return participant.status == Status.Active && participant.kind == kind;
    }

    /// @notice Whether the account is active regardless of kind
    function isActiveParticipant(address account) external view returns (bool) {
        return _participants[account].status == Status.Active;
    }

    /// @notice Number of ever-registered participants
    function participantCount() external view returns (uint256) {
        return _accounts.length;
    }

    /// @notice Account address by registration index
    function accountAt(uint256 index) external view returns (address) {
        return _accounts[index];
    }

    /// @dev Returns the participant only when it is active
    function _active(address account) private view returns (Participant storage participant) {
        participant = _participants[account];
        if (!_known[account]) revert NotRegistered(account);
        if (participant.status != Status.Active) revert WrongStatus(account, participant.status);
    }
}
