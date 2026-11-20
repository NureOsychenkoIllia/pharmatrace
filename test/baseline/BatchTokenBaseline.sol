// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

import {IParticipantRegistry} from "../../src/interfaces/IParticipantRegistry.sol";

/// @notice Isolated packing benchmark with the unoptimized field order (nine slots).
contract PackBaseline is ERC721, AccessControl {
    struct Batch {
        bytes32 productId;
        uint64 serial;
        address manufacturer;
        address custodian;
        uint64 expiry;
        uint64 createdAt;
        uint8 state;
        address pendingRecipient;
        uint128 quantity;
        uint128 parentId;
        bytes32 metadataHash;
        bytes2 originCity;
        bool flagged;
        uint16 anomalyScore;
        bytes32 modelVersion;
        bytes32 dataHash;
    }

    IParticipantRegistry public immutable REGISTRY;
    uint256 public batchCount;
    mapping(uint256 => Batch) private _batches;

    error NotManufacturer(address account);

    constructor(address admin, IParticipantRegistry registry) ERC721("PackBaseline", "PB") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        REGISTRY = registry;
    }

    function mint(
        bytes32 productId,
        uint64 serial,
        uint64 expiry,
        uint128 quantity,
        bytes32 metadataHash,
        bytes2 originCity
    ) external returns (uint256 tokenId) {
        if (!REGISTRY.isActive(msg.sender, IParticipantRegistry.Kind.Manufacturer)) {
            revert NotManufacturer(msg.sender);
        }
        tokenId = ++batchCount;
        _batches[tokenId] = Batch({
            productId: productId,
            serial: serial,
            manufacturer: msg.sender,
            custodian: msg.sender,
            expiry: expiry,
            createdAt: uint64(block.timestamp),
            state: 1,
            pendingRecipient: address(0),
            quantity: quantity,
            parentId: 0,
            metadataHash: metadataHash,
            originCity: originCity,
            flagged: false,
            anomalyScore: 0,
            modelVersion: bytes32(0),
            dataHash: bytes32(0)
        });
        _mint(msg.sender, tokenId);
    }

    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721, AccessControl)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }
}

/// @notice Same benchmark with the optimized field order (eight slots).
contract PackOptimized is ERC721, AccessControl {
    struct Batch {
        bytes32 productId;
        bytes32 metadataHash;
        bytes32 modelVersion;
        bytes32 dataHash;
        address manufacturer;
        uint64 serial;
        uint16 anomalyScore;
        bool flagged;
        uint8 state;
        address custodian;
        uint64 expiry;
        bytes2 originCity;
        address pendingRecipient;
        uint64 createdAt;
        uint128 quantity;
        uint128 parentId;
    }

    IParticipantRegistry public immutable REGISTRY;
    uint256 public batchCount;
    mapping(uint256 => Batch) private _batches;

    error NotManufacturer(address account);

    constructor(address admin, IParticipantRegistry registry) ERC721("PackOptimized", "PO") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        REGISTRY = registry;
    }

    function mint(
        bytes32 productId,
        uint64 serial,
        uint64 expiry,
        uint128 quantity,
        bytes32 metadataHash,
        bytes2 originCity
    ) external returns (uint256 tokenId) {
        if (!REGISTRY.isActive(msg.sender, IParticipantRegistry.Kind.Manufacturer)) {
            revert NotManufacturer(msg.sender);
        }
        tokenId = ++batchCount;
        _batches[tokenId] = Batch({
            productId: productId,
            metadataHash: metadataHash,
            modelVersion: bytes32(0),
            dataHash: bytes32(0),
            manufacturer: msg.sender,
            serial: serial,
            anomalyScore: 0,
            flagged: false,
            state: 1,
            custodian: msg.sender,
            expiry: expiry,
            originCity: originCity,
            pendingRecipient: address(0),
            createdAt: uint64(block.timestamp),
            quantity: quantity,
            parentId: 0
        });
        _mint(msg.sender, tokenId);
    }

    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721, AccessControl)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }
}

/// @notice Same packing as PackOptimized but the registry is a storage variable.
contract PackStorageRegistry is ERC721, AccessControl {
    struct Batch {
        bytes32 productId;
        bytes32 metadataHash;
        bytes32 modelVersion;
        bytes32 dataHash;
        address manufacturer;
        uint64 serial;
        uint16 anomalyScore;
        bool flagged;
        uint8 state;
        address custodian;
        uint64 expiry;
        bytes2 originCity;
        address pendingRecipient;
        uint64 createdAt;
        uint128 quantity;
        uint128 parentId;
    }

    IParticipantRegistry public registry;
    uint256 public batchCount;
    mapping(uint256 => Batch) private _batches;

    error NotManufacturer(address account);

    constructor(address admin, IParticipantRegistry registry_) ERC721("PackStorage", "PS") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        registry = registry_;
    }

    function mint(
        bytes32 productId,
        uint64 serial,
        uint64 expiry,
        uint128 quantity,
        bytes32 metadataHash,
        bytes2 originCity
    ) external returns (uint256 tokenId) {
        if (!registry.isActive(msg.sender, IParticipantRegistry.Kind.Manufacturer)) {
            revert NotManufacturer(msg.sender);
        }
        tokenId = ++batchCount;
        _batches[tokenId] = Batch({
            productId: productId,
            metadataHash: metadataHash,
            modelVersion: bytes32(0),
            dataHash: bytes32(0),
            manufacturer: msg.sender,
            serial: serial,
            anomalyScore: 0,
            flagged: false,
            state: 1,
            custodian: msg.sender,
            expiry: expiry,
            originCity: originCity,
            pendingRecipient: address(0),
            createdAt: uint64(block.timestamp),
            quantity: quantity,
            parentId: 0
        });
        _mint(msg.sender, tokenId);
    }

    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721, AccessControl)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }
}

/// @notice Revert-string baseline for the custom-error comparison.
contract RevertStrings {
    function fail() external pure {
        require(false, "not manufacturer");
    }
}

/// @notice Custom-error variant for the same failure.
contract RevertCustom {
    error NotManufacturer(address account);

    function fail() external view {
        revert NotManufacturer(msg.sender);
    }
}
