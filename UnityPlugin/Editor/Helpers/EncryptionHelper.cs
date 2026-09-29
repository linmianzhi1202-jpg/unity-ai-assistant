using System;
using System.IO;
using System.Security.Cryptography;

namespace UnityMCP.Editor.Helpers
{
    /// <summary>
    /// AES-256-GCM encryption helper for Unity.
    /// Provides encryption/decryption for sensitive data in transit and at rest.
    /// </summary>
    public static class EncryptionHelper
    {
        private const int KeySize = 32;     // 256 bits
        private const int NonceSize = 12;   // 96 bits

        /// <summary>
        /// Generate a new random AES-256 key as base64 string.
        /// </summary>
        public static string GenerateKey()
        {
            var key = new byte[KeySize];
            using (var rng = RandomNumberGenerator.Create())
            {
                rng.GetBytes(key);
            }
            return Convert.ToBase64String(key);
        }

        /// <summary>
        /// Encrypt a string using AES-256-GCM.
        /// </summary>
        /// <param name="plaintext">The string to encrypt.</param>
        /// <param name="keyBase64">Base64-encoded 256-bit key.</param>
        /// <returns>Base64-encoded nonce + ciphertext + tag.</returns>
        public static string Encrypt(string plaintext, string keyBase64)
        {
            var key = Convert.FromBase64String(keyBase64);
            if (key.Length != KeySize)
                throw new ArgumentException($"Key must be {KeySize} bytes, got {key.Length}");

            var nonce = new byte[NonceSize];
            using (var rng = RandomNumberGenerator.Create())
            {
                rng.GetBytes(nonce);
            }

            var plaintextBytes = System.Text.Encoding.UTF8.GetBytes(plaintext);
            var ciphertext = new byte[plaintextBytes.Length]; // .NET Standard 2.1: ciphertext length = plaintext length
            var tag = new byte[16];

            using (var aes = new AesGcm(key))
            {
                aes.Encrypt(nonce, plaintextBytes, ciphertext, tag);
            }

            // Combine: nonce + ciphertext + tag
            var combined = new byte[nonce.Length + ciphertext.Length + tag.Length];
            Buffer.BlockCopy(nonce, 0, combined, 0, nonce.Length);
            Buffer.BlockCopy(ciphertext, 0, combined, nonce.Length, ciphertext.Length);
            Buffer.BlockCopy(tag, 0, combined, nonce.Length + ciphertext.Length, tag.Length);

            return Convert.ToBase64String(combined);
        }

        /// <summary>
        /// Decrypt a base64-encoded AES-256-GCM ciphertext.
        /// </summary>
        /// <param name="encrypted">Base64-encoded nonce + ciphertext + tag.</param>
        /// <param name="keyBase64">Base64-encoded 256-bit key.</param>
        /// <returns>The decrypted plaintext string.</returns>
        public static string Decrypt(string encrypted, string keyBase64)
        {
            var key = Convert.FromBase64String(keyBase64);
            var combined = Convert.FromBase64String(encrypted);

            var nonce = new byte[NonceSize];
            var tag = new byte[16];
            var ciphertext = new byte[combined.Length - NonceSize - 16];

            Buffer.BlockCopy(combined, 0, nonce, 0, NonceSize);
            Buffer.BlockCopy(combined, NonceSize, ciphertext, 0, ciphertext.Length);
            Buffer.BlockCopy(combined, NonceSize + ciphertext.Length, tag, 0, 16);

            var plaintext = new byte[ciphertext.Length];

            using (var aes = new AesGcm(key))
            {
                aes.Decrypt(nonce, ciphertext, tag, plaintext);
            }

            return System.Text.Encoding.UTF8.GetString(plaintext);
        }
    }
}
