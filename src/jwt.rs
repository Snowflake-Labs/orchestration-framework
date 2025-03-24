use openssl::{base64, pkey::PKey, sha::Sha256};
use jsonwebtoken::{encode, EncodingKey, Header, Algorithm};
use std::{fs::File, io::Read, time::Duration};
use serde::{Deserialize, Serialize};
use chrono::Utc;

#[derive(Serialize, Deserialize)]
pub(crate) struct Claims {
    iss: String,
    sub: String,
    iat: i64,
    exp: i64,
}

pub(crate) struct JWTGenerator {
    account: String,
    user: String,
    qualified_username: String,
    private_key: PKey<openssl::pkey::Private>,
    lifetime: Duration,
    renewal_delay: Duration,
}

impl JWTGenerator {
    pub fn new(account: &str, user: &str, private_key_path: &str, lifetime: Duration, renewal_delay: Duration) -> Self {
        let account = Self::prepare_account_name_for_jwt(account);
        let user = user.to_uppercase();
        let qualified_username = format!("{}.{}", account, user);
        let private_key = Self::load_private_key(private_key_path);

        JWTGenerator {
            account,
            user,
            qualified_username,
            private_key,
            lifetime,
            renewal_delay,
        }
    }

    fn prepare_account_name_for_jwt(raw_account: &str) -> String {
        if raw_account.contains(".global") {
            raw_account.split('-').next().unwrap_or(raw_account).to_uppercase()
        } else {
            raw_account.split('.').next().unwrap_or(raw_account).to_uppercase()
        }
    }

    fn load_private_key(path: &str) -> PKey<openssl::pkey::Private> {
        let mut file = File::open(path).expect("Failed to open private key file");
        let mut key_data = Vec::new();
        file.read_to_end(&mut key_data).expect("Failed to read private key file");

        PKey::private_key_from_pem(&key_data).expect("Failed to parse private key")
    }

    fn calculate_public_key_fingerprint(&self) -> String {
        let pub_key = self.private_key.public_key_to_pem().expect("Failed to extract public key");
        let mut hasher = Sha256::new();
        hasher.update(&pub_key);
        let fingerprint = base64::encode_block(&hasher.finish());
        format!("SHA256:{}", fingerprint)
    }

    pub fn get_token(&self) -> String {
        let now = Utc::now();
        let public_key_fp = self.calculate_public_key_fingerprint();

        let claims = Claims {
            iss: format!("{}.{}", self.qualified_username, public_key_fp),
            sub: self.qualified_username.clone(),
            iat: now.timestamp(),
            exp: (now + self.lifetime).timestamp(),
        };

        let encoding_key = EncodingKey::from_rsa_pem(&self.private_key.private_key_to_pem_pkcs8().unwrap())
            .expect("Failed to create encoding key");

        encode(&Header::new(Algorithm::RS256), &claims, &encoding_key)
            .expect("Failed to generate JWT")
    }
}
